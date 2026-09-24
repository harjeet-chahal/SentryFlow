"""Distributed rate limiting backed by Redis.

Two algorithms are supported, both implemented as Lua scripts so that the
read-modify-write cycle is atomic on the Redis server. Doing this in Python
would need a WATCH/MULTI retry loop and would still lose under contention;
a script executes as a single indivisible unit.

    sliding_window  Precise. Keeps one sorted-set entry per request, scored
                    by timestamp, and trims entries older than the window.
                    Costs O(log N) per request and one member of memory per
                    request in flight. Use when correctness at the boundary
                    matters -- a fixed window lets a caller send 2x the limit
                    across the boundary instant.

    token_bucket    Cheap and burst-friendly. Two fields per key regardless
                    of traffic, refilled lazily from elapsed time. Use when
                    you want to allow a short burst above the steady rate.

Both scripts are deterministic: every value that varies between calls
(timestamps, the sorted-set member) is passed in as an argument rather than
generated inside Lua, so the scripts are safe to replicate.
"""
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from redis.exceptions import RedisError
from fastapi.concurrency import run_in_threadpool

from backend.config import settings
from backend.redis_client import get_redis

logger = logging.getLogger(__name__)

# How long a resolved rate-limit config is cached in Redis. Short enough that
# a limit change in the dashboard takes effect quickly, long enough that the
# database is not in the per-request path.
CONFIG_CACHE_TTL = 60

# Sentinel stored for users with no override, so that a miss does not hit the
# database again on every request.
_DEFAULT_MARKER = "__default__"


SLIDING_WINDOW_SCRIPT = """
local key       = KEYS[1]
local now_ms    = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit     = tonumber(ARGV[3])
local member    = ARGV[4]

-- Drop everything that has aged out of the window.
redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)

local count = redis.call('ZCARD', key)

if count >= limit then
    -- Tell the caller when the oldest request will age out, so we can send
    -- an accurate Retry-After instead of making them poll.
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after_ms = window_ms
    if oldest[2] then
        retry_after_ms = (tonumber(oldest[2]) + window_ms) - now_ms
        if retry_after_ms < 0 then retry_after_ms = 0 end
    end
    return {0, count, 0, retry_after_ms}
end

redis.call('ZADD', key, now_ms, member)
-- Refresh the TTL on every write so idle keys evict themselves.
redis.call('PEXPIRE', key, window_ms)

return {1, count + 1, limit - (count + 1), 0}
"""


TOKEN_BUCKET_SCRIPT = """
local key          = KEYS[1]
local now_ms       = tonumber(ARGV[1])
local rate_per_sec = tonumber(ARGV[2])
local capacity     = tonumber(ARGV[3])
local requested    = tonumber(ARGV[4])

local bucket         = redis.call('HMGET', key, 'tokens', 'last_refill_ms')
local tokens         = tonumber(bucket[1])
local last_refill_ms = tonumber(bucket[2])

-- A missing key is a full bucket: a first-time caller gets the whole burst.
if tokens == nil or last_refill_ms == nil then
    tokens = capacity
    last_refill_ms = now_ms
end

-- Refill lazily from elapsed time rather than on a timer.
local elapsed_ms = math.max(0, now_ms - last_refill_ms)
tokens = math.min(capacity, tokens + (elapsed_ms / 1000.0) * rate_per_sec)

local allowed = 0
local retry_after_ms = 0
if tokens >= requested then
    allowed = 1
    tokens = tokens - requested
else
    retry_after_ms = math.ceil(((requested - tokens) / rate_per_sec) * 1000)
end

redis.call('HMSET', key, 'tokens', tokens, 'last_refill_ms', now_ms)

-- Keep the key alive for as long as it would take to refill from empty,
-- with a floor so short-lived buckets are not evicted mid-burst.
local ttl = math.ceil(capacity / rate_per_sec) * 2
if ttl < 60 then ttl = 60 end
redis.call('EXPIRE', key, ttl)

return {allowed, math.floor(tokens), capacity, retry_after_ms}
"""


@dataclass
class RateLimitResult:
    """Outcome of a rate-limit check, shaped for response headers."""

    allowed: bool
    remaining: int
    limit: int
    retry_after_seconds: int = 0
    # Unix time at which the caller regains full quota.
    reset_epoch: int = 0
    # True when the limiter could not reach Redis and the decision was made by
    # the fail-open/fail-closed policy rather than by an actual count.
    degraded: bool = False

    @property
    def headers(self) -> dict:
        # Advertise nothing while degraded. Reporting a limit of 0 would read
        # as "you have no quota" rather than "this was not enforced", and
        # clients throttle themselves on these headers.
        if self.degraded:
            headers = {}
            if not self.allowed and self.retry_after_seconds > 0:
                headers["Retry-After"] = str(self.retry_after_seconds)
            return headers

        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_epoch),
        }
        if not self.allowed and self.retry_after_seconds > 0:
            headers["Retry-After"] = str(self.retry_after_seconds)
        return headers


# Registered lazily: register_script only hashes the source locally, but
# binding it to a client at import time would freeze in whichever client
# existed then -- including the real one during tests.
_scripts = {}


def _script(name: str, source: str):
    client = get_redis()
    cached = _scripts.get(name)
    if cached is None or cached[0] is not client:
        cached = (client, client.register_script(source))
        _scripts[name] = cached
    return cached[1]


def reset_scripts() -> None:
    """Forget registered scripts so they rebind to a new client. For tests."""
    _scripts.clear()


def _load_config_from_db(user_id: str, endpoint: str) -> Optional[dict]:
    """Look up the most specific rate-limit override for this caller.

    Resolution order is exact endpoint, then a per-user wildcard, then None
    to mean "use the global defaults".
    """
    from backend.models.database import SessionLocal
    from backend.models.models import RateLimit

    db = SessionLocal()
    try:
        row = (
            db.query(RateLimit)
            .filter(RateLimit.user_id == user_id, RateLimit.endpoint == endpoint)
            .first()
        )
        if row is None:
            row = (
                db.query(RateLimit)
                .filter(RateLimit.user_id == user_id, RateLimit.endpoint == "*")
                .first()
            )
        if row is None:
            return None
        return {
            "requests_per_minute": row.requests_per_minute,
            "burst_capacity": row.burst_capacity,
            "algorithm": row.algorithm,
        }
    finally:
        db.close()


def default_config() -> dict:
    return {
        "requests_per_minute": settings.DEFAULT_REQUESTS_PER_MINUTE,
        "burst_capacity": settings.DEFAULT_BURST_CAPACITY,
        "algorithm": settings.DEFAULT_ALGORITHM,
    }


async def get_rate_limit_config(user_id: str, endpoint: str) -> dict:
    """Resolve the rate-limit config for a caller, cached in Redis.

    The database is authoritative but must not sit in the per-request path,
    so results (including "no override") are cached for CONFIG_CACHE_TTL.
    """
    cache_key = f"ratelimit:cfg:{user_id}:{endpoint}"
    redis_client = get_redis()

    try:
        cached = await redis_client.get(cache_key)
        if cached == _DEFAULT_MARKER:
            return default_config()
        if cached:
            return json.loads(cached)
    except (RedisError, ValueError):
        # A cache problem must not take the limiter down; fall through to the
        # database and let the request proceed on a slower path.
        logger.warning("Rate-limit config cache read failed", exc_info=True)

    config = await run_in_threadpool(_load_config_from_db, user_id, endpoint)

    try:
        payload = _DEFAULT_MARKER if config is None else json.dumps(config)
        await redis_client.set(cache_key, payload, ex=CONFIG_CACHE_TTL)
    except RedisError:
        logger.warning("Rate-limit config cache write failed", exc_info=True)

    return config or default_config()


async def check_sliding_window(key: str, window_seconds: int, limit: int) -> RateLimitResult:
    """Allow at most ``limit`` requests in any trailing ``window_seconds``."""
    now_ms = int(time.time() * 1000)
    window_ms = window_seconds * 1000
    # Generated here, not in Lua, to keep the script deterministic.
    member = f"{now_ms}-{uuid.uuid4().hex}"

    script = _script("sliding_window", SLIDING_WINDOW_SCRIPT)
    allowed, _used, remaining, retry_after_ms = await script(
        keys=[key], args=[now_ms, window_ms, limit, member]
    )
    retry_after_seconds = math.ceil(int(retry_after_ms) / 1000)
    # When blocked, quota returns as the oldest request ages out. When
    # allowed, the worst case is a full window from now.
    reset_in = retry_after_seconds if not allowed else window_seconds
    return RateLimitResult(
        allowed=bool(allowed),
        remaining=int(remaining),
        limit=limit,
        retry_after_seconds=retry_after_seconds,
        reset_epoch=int(now_ms / 1000) + reset_in,
    )


async def check_token_bucket(key: str, rate_per_second: float, capacity: int) -> RateLimitResult:
    """Allow a burst up to ``capacity``, refilling at ``rate_per_second``."""
    now_ms = int(time.time() * 1000)

    script = _script("token_bucket", TOKEN_BUCKET_SCRIPT)
    allowed, remaining, limit, retry_after_ms = await script(
        keys=[key], args=[now_ms, rate_per_second, capacity, 1]
    )
    # A token bucket has no window; full quota returns once it refills to
    # capacity at the configured rate.
    seconds_to_full = math.ceil((int(limit) - int(remaining)) / rate_per_second)
    return RateLimitResult(
        allowed=bool(allowed),
        remaining=int(remaining),
        limit=int(limit),
        retry_after_seconds=math.ceil(int(retry_after_ms) / 1000),
        reset_epoch=int(now_ms / 1000) + seconds_to_full,
    )


async def check_rate_limit(user_id: str, endpoint: str) -> RateLimitResult:
    """Decide whether this caller may make this request right now.

    If Redis is unreachable the behaviour is governed by
    ``RATE_LIMIT_FAIL_OPEN``. It defaults to failing open: losing the limiter
    should degrade enforcement, not turn into a full API outage.
    """
    try:
        config = await get_rate_limit_config(user_id, endpoint)
        key = f"rate:{config['algorithm']}:{user_id}:{endpoint}"

        if config["algorithm"] == "token_bucket":
            rate_per_second = config["requests_per_minute"] / 60.0
            return await check_token_bucket(key, rate_per_second, config["burst_capacity"])

        return await check_sliding_window(
            key, settings.DEFAULT_RATE_LIMIT_WINDOW, config["requests_per_minute"]
        )
    except RedisError:
        logger.error("Redis unavailable during rate-limit check", exc_info=True)
        if settings.RATE_LIMIT_FAIL_OPEN:
            return RateLimitResult(allowed=True, remaining=0, limit=0, degraded=True)
        return RateLimitResult(
            allowed=False, remaining=0, limit=0, retry_after_seconds=1, degraded=True
        )
