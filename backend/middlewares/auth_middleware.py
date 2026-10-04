"""Gateway authentication: API keys are exchanged for short-lived JWTs.

A program holds a long-lived API key but sends it to one place only,
``POST /auth/token``, which trades it for a signed gateway token. Gateway
requests carry that token as ``Authorization: Bearer <token>``, and the
gateway verifies it in-process: the signature says who the caller is, so
authenticating a request never needs the database.

A JWT on its own cannot be taken back before it expires. So revoking a key
also records its id in Redis for as long as a token issued from it could
still be valid, and the gateway checks that list on every request. That is
one Redis round trip, the one it used to spend looking up the key itself.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import NamedTuple, Optional

import jwt
from redis.exceptions import RedisError
from fastapi.concurrency import run_in_threadpool

from backend.config import JWT_SECRET, settings
from backend.redis_client import get_redis

logger = logging.getLogger(__name__)

# Dashboard tokens are signed with the same key. The type claim keeps each
# flavour out of the other's routes: a gateway token cannot manage an
# account, and a dashboard session cannot stand in for an API credential.
GATEWAY_TOKEN_TYPE = "gateway"

# Unknown keys are cached so that a client retrying with a bad key cannot
# hammer the database. Valid keys are not cached: a key is checked once per
# token rather than once per request, so revoking one needs no eviction.
_INVALID_MARKER = "__invalid__"
_INVALID_CACHE_TTL = 60

# A revocation is remembered this much longer than a token lives. That covers
# a token signed a moment after its key was revoked, and clock skew between
# replicas.
_REVOCATION_MARGIN_SECONDS = 60


class ResolvedApiKey(NamedTuple):
    user_id: str
    key_id: str


def _lookup_api_key(api_key: str) -> Optional[ResolvedApiKey]:
    """Resolve an active API key against the database.

    Also stamps ``last_used_at``. Keys are checked when a token is issued,
    not on every request, so the stamp is accurate to within one token
    lifetime -- a usage signal, not an audit trail.
    """
    from backend.models.database import SessionLocal
    from backend.models.models import ApiKey

    db = SessionLocal()
    try:
        record = (
            db.query(ApiKey)
            .filter(ApiKey.key == api_key, ApiKey.is_active.is_(True))
            .first()
        )
        if record is None:
            return None

        record.last_used_at = datetime.now(timezone.utc)
        resolved = ResolvedApiKey(user_id=record.user_id, key_id=record.id)
        db.commit()
        return resolved
    finally:
        db.close()


async def verify_api_key(api_key: Optional[str]) -> Optional[ResolvedApiKey]:
    """Return the owner and id of an active API key, or None."""
    if not api_key:
        return None

    cache_key = f"apikey:{api_key}"
    redis_client = get_redis()

    try:
        if await redis_client.get(cache_key) == _INVALID_MARKER:
            return None
    except RedisError:
        # Without the cache every unknown key reaches the database: slower,
        # but authentication must not fail open.
        logger.warning("API-key cache read failed", exc_info=True)

    resolved = await run_in_threadpool(_lookup_api_key, api_key)

    if resolved is None:
        try:
            await redis_client.set(cache_key, _INVALID_MARKER, ex=_INVALID_CACHE_TTL)
        except RedisError:
            logger.warning("API-key cache write failed", exc_info=True)

    return resolved


def issue_gateway_token(key: ResolvedApiKey) -> dict:
    """Sign a gateway token for the owner of a verified API key.

    The subject is the user's id, where dashboard tokens carry the username:
    the id is what the limiter and the usage events key on, so the gateway
    never has to look it up.
    """
    lifetime = timedelta(minutes=settings.GATEWAY_TOKEN_EXPIRE_MINUTES)
    now = datetime.now(timezone.utc)
    claims = {
        "sub": key.user_id,
        "type": GATEWAY_TOKEN_TYPE,
        # The key it was issued for, so that revoking the key can cancel it.
        "key_id": key.key_id,
        "iat": now,
        "exp": now + lifetime,
    }
    return {
        "access_token": jwt.encode(claims, JWT_SECRET, algorithm=settings.JWT_ALGORITHM),
        "token_type": "bearer",
        "expires_in": int(lifetime.total_seconds()),
    }


def _revocation_key(key_id: str) -> str:
    return f"apikey:revoked:{key_id}"


def _key_is_active(key_id: str) -> bool:
    from backend.models.database import SessionLocal
    from backend.models.models import ApiKey

    db = SessionLocal()
    try:
        return (
            db.query(ApiKey.id)
            .filter(ApiKey.id == key_id, ApiKey.is_active.is_(True))
            .first()
            is not None
        )
    finally:
        db.close()


async def _is_revoked(key_id: str) -> bool:
    try:
        return bool(await get_redis().exists(_revocation_key(key_id)))
    except RedisError:
        # The revocation list cannot be read, so ask the database whether the
        # key is still active: slower, but authentication never fails open.
        logger.warning("Revocation check failed; asking the database", exc_info=True)
        return not await run_in_threadpool(_key_is_active, key_id)


async def verify_gateway_token(token: str) -> Optional[str]:
    """Return the id of the user a gateway token was issued to, or None.

    The signature, expiry and token type are checked in-process. The only
    I/O is the revocation check.
    """
    try:
        claims = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub", "key_id"]},
        )
    except jwt.PyJWTError:
        return None

    if claims.get("type") != GATEWAY_TOKEN_TYPE:
        return None
    if await _is_revoked(claims["key_id"]):
        return None
    return claims["sub"]


async def revoke_gateway_tokens(key_id: str) -> None:
    """Cancel every unexpired token issued for a key, once the key is revoked."""
    ttl = settings.GATEWAY_TOKEN_EXPIRE_MINUTES * 60 + _REVOCATION_MARGIN_SECONDS
    try:
        await get_redis().set(_revocation_key(key_id), "1", ex=ttl)
    except RedisError:
        logger.warning(
            "Could not record the revocation of key %s; its tokens stay valid until they expire",
            key_id,
            exc_info=True,
        )
