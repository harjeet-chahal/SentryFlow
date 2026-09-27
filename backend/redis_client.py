"""Single shared async Redis client.

Both the rate limiter and the API-key cache talk to Redis on every request.
Routing them through one lazily-created ``redis.asyncio`` client means one
connection pool per process, no blocking socket I/O on the event loop, and
one place for tests to substitute a fake.
"""
import logging

from redis import asyncio as aioredis

from backend.config import settings

logger = logging.getLogger(__name__)

_client = None


def get_redis():
    """Return the process-wide async Redis client, creating it on first use.

    Creation is lazy so that importing the app does not require a reachable
    Redis -- which is what lets the test suite swap in a fake first.
    """
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def set_redis(client) -> None:
    """Override the shared client. Intended for tests."""
    global _client
    _client = client


def reset_redis() -> None:
    """Drop the cached client so the next call rebuilds it."""
    global _client
    _client = None


async def close_redis() -> None:
    """Close the shared client on application shutdown.

    Tolerant by design: shutdown must not raise, and the close method is
    named ``aclose`` on current redis-py but ``close`` on older releases.
    """
    global _client
    if _client is None:
        return
    closer = getattr(_client, "aclose", None) or getattr(_client, "close", None)
    try:
        if closer is not None:
            await closer()
    except Exception:  # noqa: BLE001 - never fail a shutdown
        logger.warning("Error closing Redis client", exc_info=True)
    finally:
        _client = None
