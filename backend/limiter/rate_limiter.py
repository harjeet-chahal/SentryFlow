import time
import redis
import json
from typing import Tuple, Optional
import os

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Default rate limits if not specified in database
DEFAULT_REQUESTS_PER_MINUTE = 60
DEFAULT_BURST_CAPACITY = 10

# Lua script for sliding window rate limiting (atomic operation)
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

-- Remove timestamps older than the window
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

-- Count requests in the current window
local count = redis.call('ZCARD', key)

-- Check if we're over the limit
if count >= limit then
    return {0, count, limit - count}
end

-- Add the current timestamp
redis.call('ZADD', key, now, now .. '-' .. math.random())

-- Set expiry on the key
redis.call('EXPIRE', key, window)

return {1, count + 1, limit - (count + 1)}
"""

# Lua script for token bucket rate limiting
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])  -- tokens per second
local capacity = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

-- Get the current bucket state or create a new one
local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1] or capacity)
local last_refill = tonumber(bucket[2] or 0)

-- Calculate tokens to add based on time elapsed
local delta = math.max(0, now - last_refill)
local new_tokens = math.min(capacity, tokens + (delta * rate))

-- Check if we have enough tokens
if new_tokens < requested then
    return {0, new_tokens, capacity}
end

-- Consume tokens and update the bucket
redis.call('HMSET', key, 'tokens', new_tokens - requested, 'last_refill', now)
redis.call('EXPIRE', key, math.ceil(capacity / rate) * 2)  -- Set TTL to 2x the time to refill

return {1, new_tokens - requested, capacity}
"""

# Load Lua scripts
sliding_window_lua = redis_client.register_script(SLIDING_WINDOW_SCRIPT)
token_bucket_lua = redis_client.register_script(TOKEN_BUCKET_SCRIPT)


async def get_rate_limit_config(user_id: str, endpoint: str) -> dict:
    """Get rate limit configuration for a user and endpoint.
    
    In a real implementation, this would fetch from the database.
    For now, we'll use default values.
    """
    # TODO: Fetch from database based on user_id and endpoint
    return {
        "requests_per_minute": DEFAULT_REQUESTS_PER_MINUTE,
        "burst_capacity": DEFAULT_BURST_CAPACITY,
        "algorithm": "sliding_window"  # or "token_bucket"
    }


async def check_sliding_window(key: str, window: int, limit: int) -> Tuple[bool, int]:
    """Check if a request is allowed using the sliding window algorithm.
    
    Args:
        key: Redis key for the rate limit counter
        window: Time window in seconds
        limit: Maximum number of requests allowed in the window
        
    Returns:
        Tuple of (is_allowed, remaining_requests)
    """
    now = int(time.time())
    result = sliding_window_lua(keys=[key], args=[now, window, limit])
    is_allowed, _, remaining = result
    return bool(is_allowed), remaining


async def check_token_bucket(key: str, rate: float, capacity: int) -> Tuple[bool, int]:
    """Check if a request is allowed using the token bucket algorithm.
    
    Args:
        key: Redis key for the token bucket
        rate: Token refill rate per second
        capacity: Maximum bucket capacity
        
    Returns:
        Tuple of (is_allowed, remaining_tokens)
    """
    now = time.time()
    result = token_bucket_lua(keys=[key], args=[now, rate, capacity, 1])
    is_allowed, remaining, _ = result
    return bool(is_allowed), int(remaining)


async def check_rate_limit(user_id: str, endpoint: str) -> Tuple[bool, int]:
    """Check if a request is allowed based on rate limits.
    
    Args:
        user_id: The user ID making the request
        endpoint: The API endpoint being accessed
        
    Returns:
        Tuple of (is_allowed, remaining_requests)
    """
    # Get rate limit configuration
    config = await get_rate_limit_config(user_id, endpoint)
    
    # Create Redis key
    key = f"rate:{user_id}:{endpoint}"
    
    # Check rate limit based on algorithm
    if config["algorithm"] == "token_bucket":
        # Convert requests_per_minute to tokens per second
        rate = config["requests_per_minute"] / 60.0
        capacity = config["burst_capacity"]
        return await check_token_bucket(key, rate, capacity)
    else:  # Default to sliding window
        window = 60  # 1 minute in seconds
        limit = config["requests_per_minute"]
        return await check_sliding_window(key, window, limit)