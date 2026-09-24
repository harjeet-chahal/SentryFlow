"""Usage logging to Kafka.

Every proxied request emits one event that the aggregator later folds into
ClickHouse. This sits in the request path, so it is deliberately
fire-and-forget: we hand the record to the producer's local buffer and return
immediately rather than waiting for a broker acknowledgement. Waiting would
put full Kafka round-trip latency on every client request, and analytics are
not worth that.

The consequence is that a broker outage loses events rather than failing
requests. That is the right trade for usage analytics; it would be the wrong
trade for billing.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from backend.config import settings

logger = logging.getLogger(__name__)

_producer: Optional[AIOKafkaProducer] = None
# Guards start-up so that concurrent first requests cannot each build a producer.
_producer_lock = asyncio.Lock()


async def start_producer() -> Optional[AIOKafkaProducer]:
    """Start the shared producer. Called once from the app's startup hook."""
    global _producer
    async with _producer_lock:
        if _producer is not None:
            return _producer
        try:
            producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                # Batch briefly so a burst of requests becomes a few produce
                # calls rather than one per request.
                linger_ms=20,
                acks=1,
            )
            await producer.start()
            _producer = producer
            logger.info("Kafka producer started (%s)", settings.KAFKA_BOOTSTRAP_SERVERS)
        except (KafkaError, OSError):
            # Analytics are best-effort. Booting without Kafka is allowed; the
            # gateway still authenticates, rate limits and serves traffic.
            logger.warning("Kafka unavailable at startup; usage logging disabled", exc_info=True)
            _producer = None
        return _producer


def get_producer() -> Optional[AIOKafkaProducer]:
    """Return the shared producer, or None if Kafka never came up."""
    return _producer


def set_producer(producer) -> None:
    """Override the shared producer. Intended for tests."""
    global _producer
    _producer = producer


def build_event(user_id: str, endpoint: str, status_code: int, response_time_ms: int) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "endpoint": endpoint,
        "status_code": status_code,
        "response_time": response_time_ms,
    }


async def log_request(user_id: str, endpoint: str, status_code: int, response_time_ms: int) -> bool:
    """Emit one usage event. Returns whether it was handed to the producer.

    Never raises: a logging failure must not turn a successful request into
    an error for the caller.
    """
    producer = get_producer()
    if producer is None:
        return False

    event = build_event(user_id, endpoint, status_code, response_time_ms)
    # Rate-limit rejections go to their own topic so the aggregator can build
    # throttling dashboards without scanning all traffic.
    topic = (
        settings.RATE_LIMITED_TOPIC if status_code == 429 else settings.API_REQUESTS_TOPIC
    )

    try:
        # send() buffers and returns a future; we intentionally do not await
        # delivery. Partitioning by user keeps one user's events ordered.
        await producer.send(topic, event, key=user_id.encode("utf-8"))
        return True
    except (KafkaError, OSError, ValueError):
        logger.warning("Failed to enqueue usage event", exc_info=True)
        return False


async def shutdown() -> None:
    """Flush and stop the producer on application shutdown."""
    global _producer
    if _producer is not None:
        try:
            await _producer.stop()
        except (KafkaError, OSError):
            logger.warning("Error stopping Kafka producer", exc_info=True)
        finally:
            _producer = None
