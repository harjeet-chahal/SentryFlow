"""API-key resolution and its caching behaviour."""
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from backend import redis_client
from backend.config import settings
from backend.middlewares import auth_middleware
from backend.middlewares.auth_middleware import invalidate_api_key, verify_api_key
from backend.models.database import SessionLocal
from backend.models.models import ApiKey, User


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


async def test_empty_key_is_rejected_without_a_lookup():
    assert await verify_api_key("") is None
    assert await verify_api_key(None) is None


async def test_valid_key_resolves_to_its_user():
    _seed_key()
    assert await verify_api_key("k" * 64) == "u1"


async def test_unknown_key_returns_none():
    assert await verify_api_key("z" * 64) is None


async def test_inactive_key_is_rejected():
    _seed_key(active=False)
    assert await verify_api_key("k" * 64) is None


async def test_resolved_key_is_cached(fake_redis):
    _seed_key()
    await verify_api_key("k" * 64)
    assert await fake_redis.get(f"apikey:{'k' * 64}") == "u1"


async def test_cache_hit_avoids_the_database(monkeypatch):
    _seed_key()
    await verify_api_key("k" * 64)  # populate

    def explode(api_key):
        raise AssertionError("database should not be consulted on a cache hit")

    monkeypatch.setattr(auth_middleware, "_lookup_api_key", explode)
    assert await verify_api_key("k" * 64) == "u1"


async def test_invalid_keys_are_negatively_cached(fake_redis):
    """Stops a flood of bogus keys from hammering the database."""
    await verify_api_key("z" * 64)
    assert await fake_redis.get(f"apikey:{'z' * 64}") == auth_middleware._INVALID_MARKER

    result = await verify_api_key("z" * 64)
    assert result is None


async def test_last_used_at_is_stamped():
    _seed_key()
    await verify_api_key("k" * 64)

    db = SessionLocal()
    try:
        record = db.query(ApiKey).filter(ApiKey.key == "k" * 64).first()
    finally:
        db.close()
    assert record.last_used_at is not None


class BrokenRedis:
    async def get(self, *a, **k):
        raise RedisConnectionError("down")

    async def set(self, *a, **k):
        raise RedisConnectionError("down")

    async def delete(self, *a, **k):
        raise RedisConnectionError("down")


async def test_authentication_still_works_when_the_cache_is_down():
    """A cache outage degrades to database-per-request, never fails open."""
    _seed_key()
    redis_client.set_redis(BrokenRedis())

    assert await verify_api_key("k" * 64) == "u1"


async def test_authentication_does_not_fail_open_when_the_cache_is_down():
    redis_client.set_redis(BrokenRedis())
    assert await verify_api_key("z" * 64) is None


async def test_invalidate_removes_the_cached_entry(fake_redis):
    _seed_key()
    await verify_api_key("k" * 64)
    await invalidate_api_key("k" * 64)
    assert await fake_redis.get(f"apikey:{'k' * 64}") is None


async def test_invalidate_tolerates_a_cache_outage():
    redis_client.set_redis(BrokenRedis())
    await invalidate_api_key("k" * 64)  # must not raise
