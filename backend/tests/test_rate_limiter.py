"""Rate limiter tests.

These exercise the actual Lua scripts through fakeredis rather than mocking
the Redis calls, so the algorithms themselves are under test -- including the
boundary behaviour that is the whole reason for choosing a sliding window.
"""
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.config import settings
from backend.limiter import rate_limiter
from backend.limiter.rate_limiter import (
    RateLimitResult,
    check_rate_limit,
    check_sliding_window,
    check_token_bucket,
    default_config,
    get_rate_limit_config,
)
from backend.models.database import SessionLocal
from backend.models.models import RateLimit, User


class FakeClock:
    """Stands in for the ``time`` module so tests control the window."""

    def __init__(self, start=1_700_000_000.0):
        self._now = start

    def time(self):
        return self._now

    def advance(self, seconds):
        self._now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(rate_limiter, "time", fake)
    return fake


# --------------------------------------------------------------------------
# Sliding window
# --------------------------------------------------------------------------

async def test_sliding_window_allows_up_to_the_limit(clock):
    for expected_remaining in (2, 1, 0):
        result = await check_sliding_window("k", window_seconds=60, limit=3)
        assert result.allowed is True
        assert result.remaining == expected_remaining


async def test_sliding_window_blocks_past_the_limit(clock):
    for _ in range(3):
        await check_sliding_window("k", window_seconds=60, limit=3)

    result = await check_sliding_window("k", window_seconds=60, limit=3)
    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after_seconds > 0


async def test_sliding_window_retry_after_reflects_oldest_entry(clock):
    await check_sliding_window("k", window_seconds=60, limit=1)
    clock.advance(20)

    result = await check_sliding_window("k", window_seconds=60, limit=1)
    assert result.allowed is False
    # The first request ages out 60s after it landed, i.e. 40s from now.
    assert result.retry_after_seconds == pytest.approx(40, abs=1)


async def test_sliding_window_admits_again_once_requests_age_out(clock):
    for _ in range(3):
        await check_sliding_window("k", window_seconds=60, limit=3)
    assert (await check_sliding_window("k", window_seconds=60, limit=3)).allowed is False

    clock.advance(61)

    result = await check_sliding_window("k", window_seconds=60, limit=3)
    assert result.allowed is True


async def test_sliding_window_has_no_fixed_window_boundary_burst(clock):
    """The property that motivates a sliding window over a fixed one.

    A fixed window would let 3 requests land at the end of one window and 3
    more at the start of the next -- 6 in a near-instant. A sliding window
    keeps counting backwards, so it does not.
    """
    for _ in range(3):
        assert (await check_sliding_window("k", 60, 3)).allowed is True

    # Step just past a nominal fixed-window boundary.
    clock.advance(31)
    assert (await check_sliding_window("k", 60, 3)).allowed is False


async def test_sliding_window_isolates_keys(clock):
    await check_sliding_window("user-a", 60, 1)
    assert (await check_sliding_window("user-a", 60, 1)).allowed is False
    assert (await check_sliding_window("user-b", 60, 1)).allowed is True


# --------------------------------------------------------------------------
# Token bucket
# --------------------------------------------------------------------------

async def test_token_bucket_starts_full(clock):
    result = await check_token_bucket("k", rate_per_second=1.0, capacity=5)
    assert result.allowed is True
    assert result.remaining == 4


async def test_token_bucket_allows_a_burst_then_blocks(clock):
    for _ in range(5):
        assert (await check_token_bucket("k", rate_per_second=1.0, capacity=5)).allowed is True

    blocked = await check_token_bucket("k", rate_per_second=1.0, capacity=5)
    assert blocked.allowed is False
    assert blocked.retry_after_seconds >= 1


async def test_token_bucket_refills_over_time(clock):
    for _ in range(5):
        await check_token_bucket("k", rate_per_second=1.0, capacity=5)
    assert (await check_token_bucket("k", 1.0, 5)).allowed is False

    clock.advance(3)

    # Three seconds at one token per second buys exactly three requests.
    for _ in range(3):
        assert (await check_token_bucket("k", 1.0, 5)).allowed is True
    assert (await check_token_bucket("k", 1.0, 5)).allowed is False


async def test_token_bucket_refill_is_capped_at_capacity(clock):
    await check_token_bucket("k", rate_per_second=1.0, capacity=5)
    clock.advance(10_000)  # Far more refill than the bucket can hold.

    for _ in range(5):
        assert (await check_token_bucket("k", 1.0, 5)).allowed is True
    assert (await check_token_bucket("k", 1.0, 5)).allowed is False


# --------------------------------------------------------------------------
# Config resolution
# --------------------------------------------------------------------------

def _seed_user(user_id="u1"):
    db = SessionLocal()
    try:
        db.add(User(id=user_id, username=user_id, email=f"{user_id}@e.com", hashed_password="x"))
        db.commit()
    finally:
        db.close()


def _seed_limit(user_id, endpoint, rpm=10, burst=4, algorithm="token_bucket"):
    db = SessionLocal()
    try:
        db.add(
            RateLimit(
                user_id=user_id,
                endpoint=endpoint,
                requests_per_minute=rpm,
                burst_capacity=burst,
                algorithm=algorithm,
            )
        )
        db.commit()
    finally:
        db.close()


async def test_config_falls_back_to_defaults():
    _seed_user()
    assert await get_rate_limit_config("u1", "/api/v1/hello") == default_config()


async def test_config_prefers_an_exact_endpoint_override():
    _seed_user()
    _seed_limit("u1", "/api/v1/hello", rpm=10, algorithm="token_bucket")

    config = await get_rate_limit_config("u1", "/api/v1/hello")
    assert config["requests_per_minute"] == 10
    assert config["algorithm"] == "token_bucket"


async def test_config_falls_back_to_a_user_wildcard():
    _seed_user()
    _seed_limit("u1", "*", rpm=25, algorithm="sliding_window")

    config = await get_rate_limit_config("u1", "/anything")
    assert config["requests_per_minute"] == 25


async def test_exact_endpoint_beats_wildcard():
    _seed_user()
    _seed_limit("u1", "*", rpm=25)
    _seed_limit("u1", "/api/v1/hello", rpm=99)

    config = await get_rate_limit_config("u1", "/api/v1/hello")
    assert config["requests_per_minute"] == 99


async def test_config_is_cached_so_the_database_stays_off_the_hot_path(monkeypatch):
    _seed_user()
    _seed_limit("u1", "/api/v1/hello", rpm=10)

    calls = []
    original = rate_limiter._load_config_from_db

    def counting(user_id, endpoint):
        calls.append((user_id, endpoint))
        return original(user_id, endpoint)

    monkeypatch.setattr(rate_limiter, "_load_config_from_db", counting)

    await get_rate_limit_config("u1", "/api/v1/hello")
    await get_rate_limit_config("u1", "/api/v1/hello")
    await get_rate_limit_config("u1", "/api/v1/hello")

    assert len(calls) == 1, "config lookup should be served from cache after the first miss"


async def test_absence_of_an_override_is_also_cached(monkeypatch):
    """Negative caching: users on defaults must not query the DB every request."""
    _seed_user()

    calls = []
    monkeypatch.setattr(
        rate_limiter, "_load_config_from_db", lambda u, e: calls.append((u, e)) or None
    )

    await get_rate_limit_config("u1", "/x")
    await get_rate_limit_config("u1", "/x")

    assert len(calls) == 1


# --------------------------------------------------------------------------
# Dispatch and failure modes
# --------------------------------------------------------------------------

async def test_check_rate_limit_dispatches_to_token_bucket():
    _seed_user()
    _seed_limit("u1", "*", rpm=60, burst=2, algorithm="token_bucket")

    assert (await check_rate_limit("u1", "/x")).allowed is True
    assert (await check_rate_limit("u1", "/x")).allowed is True
    assert (await check_rate_limit("u1", "/x")).allowed is False


async def test_check_rate_limit_dispatches_to_sliding_window():
    _seed_user()
    _seed_limit("u1", "*", rpm=2, algorithm="sliding_window")

    assert (await check_rate_limit("u1", "/x")).allowed is True
    assert (await check_rate_limit("u1", "/x")).allowed is True
    assert (await check_rate_limit("u1", "/x")).allowed is False


async def test_algorithms_keep_separate_key_namespaces():
    """Switching a user's algorithm must not inherit the other's counters."""
    _seed_user()
    _seed_limit("u1", "*", rpm=60, burst=1, algorithm="token_bucket")
    assert (await check_rate_limit("u1", "/x")).allowed is True
    assert (await check_rate_limit("u1", "/x")).allowed is False

    db = SessionLocal()
    try:
        db.query(RateLimit).update({"algorithm": "sliding_window"})
        db.commit()
    finally:
        db.close()
    # Bypass the config cache the way a limit change would.
    from backend.redis_client import get_redis

    await get_redis().flushdb()

    assert (await check_rate_limit("u1", "/x")).allowed is True


class ExplodingRedis:
    """A client whose every operation fails, to test degraded behaviour."""

    def register_script(self, source):
        raise RedisConnectionError("redis is down")

    async def get(self, *a, **k):
        raise RedisConnectionError("redis is down")

    async def set(self, *a, **k):
        raise RedisConnectionError("redis is down")


async def test_fails_open_when_redis_is_unreachable(monkeypatch):
    """A limiter outage should degrade enforcement, not cause an API outage."""
    from backend import redis_client

    redis_client.set_redis(ExplodingRedis())
    rate_limiter.reset_scripts()
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)

    result = await check_rate_limit("u1", "/x")
    assert result.allowed is True


async def test_fails_closed_when_configured_to(monkeypatch):
    from backend import redis_client

    redis_client.set_redis(ExplodingRedis())
    rate_limiter.reset_scripts()
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", False)

    result = await check_rate_limit("u1", "/x")
    assert result.allowed is False
    assert result.retry_after_seconds >= 1


# --------------------------------------------------------------------------
# Result shaping
# --------------------------------------------------------------------------

def test_headers_expose_limit_and_remaining():
    headers = RateLimitResult(allowed=True, remaining=7, limit=10).headers
    assert headers["X-RateLimit-Limit"] == "10"
    assert headers["X-RateLimit-Remaining"] == "7"
    assert "Retry-After" not in headers


def test_headers_include_retry_after_when_blocked():
    headers = RateLimitResult(
        allowed=False, remaining=0, limit=10, retry_after_seconds=30
    ).headers
    assert headers["Retry-After"] == "30"


def test_headers_never_report_negative_remaining():
    headers = RateLimitResult(allowed=False, remaining=-3, limit=10).headers
    assert headers["X-RateLimit-Remaining"] == "0"


def test_degraded_results_advertise_no_limit_headers():
    """A limit of 0 would read as "no quota" rather than "not enforced"."""
    headers = RateLimitResult(allowed=True, remaining=0, limit=0, degraded=True).headers
    assert "X-RateLimit-Limit" not in headers
    assert "X-RateLimit-Remaining" not in headers


def test_degraded_rejection_still_sends_retry_after():
    headers = RateLimitResult(
        allowed=False, remaining=0, limit=0, retry_after_seconds=1, degraded=True
    ).headers
    assert headers == {"Retry-After": "1"}


async def test_fail_open_result_is_marked_degraded(monkeypatch):
    from backend import redis_client

    redis_client.set_redis(ExplodingRedis())
    rate_limiter.reset_scripts()
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)

    assert (await check_rate_limit("u1", "/x")).degraded is True


async def test_sliding_window_reset_is_a_full_window_when_allowed(clock):
    result = await check_sliding_window("k", window_seconds=60, limit=3)
    assert result.reset_epoch == int(clock.time()) + 60


async def test_sliding_window_reset_tracks_the_oldest_entry_when_blocked(clock):
    await check_sliding_window("k", window_seconds=60, limit=1)
    clock.advance(20)

    result = await check_sliding_window("k", window_seconds=60, limit=1)
    assert result.allowed is False
    # The blocking request ages out 60s after it landed, i.e. 40s from now.
    assert result.reset_epoch == pytest.approx(int(clock.time()) + 40, abs=1)


async def test_token_bucket_reset_is_time_to_refill_to_capacity(clock):
    # Spend two of five tokens; at 1/s that is 2s back to full.
    await check_token_bucket("k", rate_per_second=1.0, capacity=5)
    result = await check_token_bucket("k", rate_per_second=1.0, capacity=5)

    assert result.remaining == 3
    assert result.reset_epoch == int(clock.time()) + 2


def test_reset_header_is_exposed():
    headers = RateLimitResult(
        allowed=True, remaining=7, limit=10, reset_epoch=1700000060
    ).headers
    assert headers["X-RateLimit-Reset"] == "1700000060"


# --------------------------------------------------------------------------
# Cache invalidation when a rule changes
# --------------------------------------------------------------------------

async def test_invalidation_clears_every_cached_endpoint_for_the_user(fake_redis):
    for key in ("ratelimit:cfg:u1:/a", "ratelimit:cfg:u1:/b", "ratelimit:cfg:u2:/a"):
        await fake_redis.set(key, "cached")

    await rate_limiter.invalidate_config_cache("u1")

    assert await fake_redis.get("ratelimit:cfg:u1:/a") is None
    assert await fake_redis.get("ratelimit:cfg:u1:/b") is None
    assert await fake_redis.get("ratelimit:cfg:u2:/a") == "cached"


async def test_invalidation_matches_the_user_id_literally(fake_redis):
    """A user id is data, not a glob: "u*" must not clear user "u1"."""
    await fake_redis.set("ratelimit:cfg:u1:/a", "cached")
    await fake_redis.set("ratelimit:cfg:u*:/a", "cached")

    await rate_limiter.invalidate_config_cache("u*")

    assert await fake_redis.get("ratelimit:cfg:u1:/a") == "cached"
    assert await fake_redis.get("ratelimit:cfg:u*:/a") is None


async def test_invalidation_with_nothing_cached_is_a_no_op(fake_redis):
    await rate_limiter.invalidate_config_cache("nobody")


async def test_invalidation_survives_a_redis_outage(monkeypatch, caplog):
    class DownRedis:
        def scan_iter(self, **kwargs):
            raise RedisConnectionError("down")

    monkeypatch.setattr(rate_limiter, "get_redis", lambda: DownRedis())

    with caplog.at_level("WARNING"):
        await rate_limiter.invalidate_config_cache("u1")

    assert "invalidation failed" in caplog.text
