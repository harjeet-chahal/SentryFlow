"""Gateway authentication: resolving API keys, gateway tokens, revocation."""
from datetime import datetime, timedelta, timezone

import jwt
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import event

from backend import redis_client
from backend.config import JWT_SECRET, settings
from backend.middlewares import auth_middleware
from backend.middlewares.auth_middleware import (
    ResolvedApiKey,
    issue_gateway_token,
    revoke_gateway_tokens,
    verify_api_key,
    verify_gateway_token,
)
from backend.models import database
from backend.models.database import SessionLocal
from backend.models.models import ApiKey, User

KEY = ResolvedApiKey(user_id="u1", key_id="id-kkkkkk")


def _seed_key(key="k" * 64, user_id="u1", active=True):
    db = SessionLocal()
    try:
        if db.query(User).filter(User.id == user_id).first() is None:
            db.add(
                User(id=user_id, username=user_id, email=f"{user_id}@e.com", hashed_password="x")
            )
        db.add(ApiKey(id=f"id-{key[:6]}", key=key, name="n", user_id=user_id, is_active=active))
        db.commit()
    finally:
        db.close()


def _deactivate(key_id):
    db = SessionLocal()
    try:
        db.query(ApiKey).filter(ApiKey.id == key_id).update({"is_active": False})
        db.commit()
    finally:
        db.close()


class BrokenRedis:
    async def get(self, *a, **k):
        raise RedisConnectionError("down")

    async def set(self, *a, **k):
        raise RedisConnectionError("down")

    async def exists(self, *a, **k):
        raise RedisConnectionError("down")


# --------------------------------------------------------------------------
# Resolving API keys, which happens once per token
# --------------------------------------------------------------------------

async def test_empty_key_is_rejected_without_a_lookup():
    assert await verify_api_key("") is None
    assert await verify_api_key(None) is None


async def test_valid_key_resolves_to_its_user_and_id():
    _seed_key()
    assert await verify_api_key("k" * 64) == KEY


async def test_unknown_key_returns_none():
    assert await verify_api_key("z" * 64) is None


async def test_inactive_key_is_rejected():
    _seed_key(active=False)
    assert await verify_api_key("k" * 64) is None


async def test_invalid_keys_are_negatively_cached(fake_redis, monkeypatch):
    """Stops a client retrying with a bad key from hammering the database."""
    await verify_api_key("z" * 64)
    assert await fake_redis.get(f"apikey:{'z' * 64}") == auth_middleware._INVALID_MARKER

    def explode(api_key):
        raise AssertionError("database should not be consulted for a cached bad key")

    monkeypatch.setattr(auth_middleware, "_lookup_api_key", explode)
    assert await verify_api_key("z" * 64) is None


async def test_valid_keys_are_not_cached(fake_redis):
    """Every check reaches the database, so a revoked key cannot be traded
    for a token on the strength of a stale cache entry."""
    _seed_key()
    await verify_api_key("k" * 64)
    assert await fake_redis.get(f"apikey:{'k' * 64}") is None

    _deactivate(KEY.key_id)
    assert await verify_api_key("k" * 64) is None


async def test_last_used_at_is_stamped():
    _seed_key()
    await verify_api_key("k" * 64)

    db = SessionLocal()
    try:
        record = db.query(ApiKey).filter(ApiKey.key == "k" * 64).first()
    finally:
        db.close()
    assert record.last_used_at is not None


async def test_keys_still_resolve_when_the_cache_is_down():
    """A cache outage sends every lookup to the database; it never fails open."""
    _seed_key()
    redis_client.set_redis(BrokenRedis())

    assert await verify_api_key("k" * 64) == KEY


async def test_unknown_keys_are_still_rejected_when_the_cache_is_down():
    redis_client.set_redis(BrokenRedis())
    assert await verify_api_key("z" * 64) is None


# --------------------------------------------------------------------------
# Gateway tokens
# --------------------------------------------------------------------------

def _decode(token):
    return jwt.decode(token, JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def _sign(**claims):
    return jwt.encode(claims, JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def test_a_token_names_the_user_and_the_key():
    claims = _decode(issue_gateway_token(KEY)["access_token"])
    assert claims["sub"] == "u1"
    assert claims["key_id"] == "id-kkkkkk"
    assert claims["type"] == "gateway"


def test_a_token_lives_for_the_configured_lifetime():
    issued = issue_gateway_token(KEY)
    claims = _decode(issued["access_token"])
    lifetime = settings.GATEWAY_TOKEN_EXPIRE_MINUTES * 60

    assert issued["token_type"] == "bearer"
    assert issued["expires_in"] == lifetime
    assert claims["exp"] - claims["iat"] == lifetime


async def test_an_issued_token_verifies_to_its_user():
    assert await verify_gateway_token(issue_gateway_token(KEY)["access_token"]) == "u1"


async def test_verifying_a_token_needs_no_database():
    """The point of the token: it says who the caller is, so there is
    nothing to look up."""
    token = issue_gateway_token(KEY)["access_token"]
    statements = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", record)
    try:
        assert await verify_gateway_token(token) == "u1"
    finally:
        event.remove(database.engine, "before_cursor_execute", record)
    assert statements == []


async def test_a_token_of_another_type_is_rejected():
    """Dashboard tokens share the signing key; the type claim tells them apart."""
    now = datetime.now(timezone.utc)
    token = _sign(sub="u1", key_id="id-kkkkkk", type="access", exp=now + timedelta(minutes=5))
    assert await verify_gateway_token(token) is None


async def test_an_expired_token_is_rejected():
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    token = _sign(sub="u1", key_id="id-kkkkkk", type="gateway", exp=past)
    assert await verify_gateway_token(token) is None


async def test_revoking_a_key_cancels_its_tokens():
    token = issue_gateway_token(KEY)["access_token"]
    await revoke_gateway_tokens(KEY.key_id)
    assert await verify_gateway_token(token) is None


async def test_revocation_is_per_key():
    other = issue_gateway_token(ResolvedApiKey(user_id="u1", key_id="id-other"))["access_token"]
    await revoke_gateway_tokens(KEY.key_id)
    assert await verify_gateway_token(other) == "u1"


async def test_a_revocation_outlives_the_tokens_it_cancels(fake_redis):
    await revoke_gateway_tokens(KEY.key_id)
    ttl = await fake_redis.ttl(f"apikey:revoked:{KEY.key_id}")
    assert ttl > settings.GATEWAY_TOKEN_EXPIRE_MINUTES * 60


async def test_an_active_key_still_works_when_redis_is_down():
    """With the revocation list unreadable, the database decides."""
    _seed_key()
    token = issue_gateway_token(KEY)["access_token"]
    redis_client.set_redis(BrokenRedis())

    assert await verify_gateway_token(token) == "u1"


async def test_a_revoked_key_stays_revoked_when_redis_is_down():
    """Authentication never fails open."""
    _seed_key(active=False)
    token = issue_gateway_token(KEY)["access_token"]
    redis_client.set_redis(BrokenRedis())

    assert await verify_gateway_token(token) is None


async def test_a_deleted_key_is_rejected_when_redis_is_down():
    token = issue_gateway_token(KEY)["access_token"]
    redis_client.set_redis(BrokenRedis())

    assert await verify_gateway_token(token) is None


async def test_revoking_tolerates_a_redis_outage():
    redis_client.set_redis(BrokenRedis())
    await revoke_gateway_tokens(KEY.key_id)  # must not raise
