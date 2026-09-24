"""API-key verification for gateway traffic.

Every proxied request carries an ``x-api-key`` header that has to be resolved
to a user before the limiter can key off it. That lookup is on the hot path,
so resolved keys are cached in Redis and the database is only consulted on a
miss.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from redis.exceptions import RedisError
from fastapi.concurrency import run_in_threadpool

from backend.config import settings
from backend.redis_client import get_redis

logger = logging.getLogger(__name__)

# Cached for misses as well as hits, so that a flood of invalid keys cannot be
# used to hammer the database.
_INVALID_MARKER = "__invalid__"
_INVALID_CACHE_TTL = 60


def _lookup_api_key(api_key: str) -> Optional[str]:
    """Resolve an API key to a user id against the database.

    Also stamps ``last_used_at``. Because hits are served from cache for
    ``API_KEY_CACHE_TTL``, this timestamp has that much granularity -- it is
    a usage signal, not an audit trail.
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
        user_id = record.user_id
        db.commit()
        return user_id
    finally:
        db.close()


async def verify_api_key(api_key: str) -> Optional[str]:
    """Return the user id behind an API key, or None if it is not valid."""
    if not api_key:
        return None

    cache_key = f"apikey:{api_key}"
    redis_client = get_redis()

    try:
        cached = await redis_client.get(cache_key)
        if cached == _INVALID_MARKER:
            return None
        if cached:
            return cached
    except RedisError:
        # Cache outage degrades us to database-per-request, which is slow but
        # still correct. Authentication must not fail open.
        logger.warning("API-key cache read failed", exc_info=True)

    user_id = await run_in_threadpool(_lookup_api_key, api_key)

    try:
        if user_id is None:
            await redis_client.set(cache_key, _INVALID_MARKER, ex=_INVALID_CACHE_TTL)
        else:
            await redis_client.set(cache_key, user_id, ex=settings.API_KEY_CACHE_TTL)
    except RedisError:
        logger.warning("API-key cache write failed", exc_info=True)

    return user_id


async def invalidate_api_key(api_key: str) -> None:
    """Evict a key from the cache, e.g. after it is revoked."""
    try:
        await get_redis().delete(f"apikey:{api_key}")
    except RedisError:
        logger.warning("API-key cache invalidation failed", exc_info=True)
