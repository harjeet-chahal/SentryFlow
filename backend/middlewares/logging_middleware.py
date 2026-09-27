"""Usage logging to Kafka.

Every proxied request emits one event that the aggregator later folds into
ClickHouse. This sits in the request path, so a request only puts its event
on a bounded in-memory queue and moves on. A background task owns the
producer and drains the queue.

Awaiting the producer in the request instead would let Kafka reach callers:
with the broker down, ``send()`` blocks for ``request_timeout_ms`` (40 s)
once a partition's buffer fills. Here only the background task waits. The
queue absorbs the gap, and once it is full further events are dropped and
counted. A broker outage therefore loses events rather than failing or
slowing requests. That is the right trade for usage analytics; it would be
the wrong trade for billing.

The same task connects to Kafka, retrying with capped exponential backoff,
so a gateway that boots before Kafka starts logging once Kafka arrives
instead of staying silent until it is restarted.
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from backend.config import settings

logger = logging.getLogger(__name__)

RETRY_INITIAL_SECONDS = 1.0
RETRY_MAX_SECONDS = 30.0
# Bounds each step of shutdown, so a dead broker cannot hold up a deploy.
SHUTDOWN_TIMEOUT_SECONDS = 5.0

# topic, key, value
Event = Tuple[str, bytes, Dict[str, Any]]


@dataclass
class PublisherStats:
    dropped: int = 0  # lost before reaching the producer: queue full, or shutdown
    failed: int = 0  # reached the producer, but Kafka did not take it
    delivering: bool = True  # whether the latest delivery succeeded


stats = PublisherStats()

_producer: Optional[AIOKafkaProducer] = None
_queue: "Optional[asyncio.Queue[Event]]" = None
_task: "Optional[asyncio.Task[None]]" = None


def _new_producer() -> AIOKafkaProducer:
    return AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        # Batch briefly so a burst of requests becomes a few produce
        # calls rather than one per request.
        linger_ms=20,
        acks=1,
    )


def backoff(attempt: int) -> float:
    """Seconds to wait after failed connection attempt number ``attempt``."""
    return min(RETRY_INITIAL_SECONDS * 2 ** attempt, RETRY_MAX_SECONDS)


async def _stop_quietly(producer) -> None:
    try:
        await asyncio.wait_for(producer.stop(), SHUTDOWN_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, KafkaError, OSError):
        logger.warning("Error stopping Kafka producer", exc_info=True)


async def _connect() -> AIOKafkaProducer:
    """Start a producer, retrying until Kafka answers."""
    attempt = 0
    while True:
        producer = _new_producer()
        try:
            await producer.start()
        except (KafkaError, OSError) as exc:
            await _stop_quietly(producer)
            delay = backoff(attempt)
            logger.warning("Kafka unavailable (%s); retrying in %.0fs", exc, delay)
            await asyncio.sleep(delay)
            attempt += 1
        except asyncio.CancelledError:
            # Shutting down mid-attempt: close the half-open client.
            await _stop_quietly(producer)
            raise
        else:
            logger.info("Kafka producer started (%s)", settings.KAFKA_BOOTSTRAP_SERVERS)
            return producer


def _delivered(error: Optional[BaseException]) -> None:
    """Record one outcome. Logs only when deliveries start or stop failing."""
    if error is None:
        if not stats.delivering:
            logger.info("Kafka is accepting usage events again")
        stats.delivering = True
        return
    stats.failed += 1
    if stats.delivering:
        logger.warning("Kafka is not accepting usage events; they are being lost: %r", error)
    stats.delivering = False


def _on_delivery(delivery: "asyncio.Future[Any]") -> None:
    if not delivery.cancelled():
        # Retrieving the exception also stops asyncio logging "Future
        # exception was never retrieved" for every event an outage loses.
        _delivered(delivery.exception())


async def _publish(queue: "asyncio.Queue[Event]") -> None:
    """Connect, then hand queued events to the producer, oldest first."""
    global _producer
    if _producer is None:
        _producer = await _connect()
    producer = _producer
    while True:
        topic, key, value = await queue.get()
        try:
            # send() only buffers; the returned future settles on delivery.
            delivery = await producer.send(topic, value, key=key)
        except asyncio.CancelledError:
            stats.dropped += 1  # shut down while waiting for buffer space
            raise
        except Exception as exc:  # noqa: BLE001 - one bad send must not stop the publisher
            _delivered(exc)
        else:
            delivery.add_done_callback(_on_delivery)
        finally:
            queue.task_done()


def _on_publisher_exit(task: "asyncio.Task[None]") -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("Kafka publisher stopped; usage logging is off", exc_info=task.exception())


async def start_producer() -> None:
    """Start the background publisher. Returns at once: boot never waits on Kafka."""
    global _queue, _task
    if _task is not None:
        return
    _queue = asyncio.Queue(maxsize=settings.USAGE_EVENT_BUFFER)
    _task = asyncio.create_task(_publish(_queue), name="kafka-publisher")
    _task.add_done_callback(_on_publisher_exit)


def get_producer() -> Optional[AIOKafkaProducer]:
    """Return the connected producer, or None while Kafka is unreachable."""
    return _producer


def set_producer(producer) -> None:
    """Override the shared producer. Intended for tests."""
    global _producer
    _producer = producer


def reset() -> None:
    """Forget all publisher state. Intended for tests."""
    global _producer, _queue, _task, stats
    _producer = _queue = _task = None
    stats = PublisherStats()


def status() -> Dict[str, Any]:
    """What /health reports about usage logging."""
    return {
        "connected": _producer is not None,
        "delivering": stats.delivering,
        "queued": _queue.qsize() if _queue is not None else 0,
        "dropped": stats.dropped,
        "failed": stats.failed,
    }


def build_event(user_id: str, endpoint: str, status_code: int, response_time_ms: int) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "endpoint": endpoint,
        "status_code": status_code,
        "response_time": response_time_ms,
    }


def log_request(user_id: str, endpoint: str, status_code: int, response_time_ms: int) -> bool:
    """Queue one usage event. Returns whether it was queued.

    Never waits and never raises: logging must not slow a request down or
    turn a successful one into an error.
    """
    if _queue is None:
        return False

    # Rate-limit rejections go to their own topic so the aggregator can build
    # throttling dashboards without scanning all traffic.
    topic = (
        settings.RATE_LIMITED_TOPIC if status_code == 429 else settings.API_REQUESTS_TOPIC
    )
    event = build_event(user_id, endpoint, status_code, response_time_ms)
    try:
        # Keyed by user, so one user's events stay ordered in one partition.
        _queue.put_nowait((topic, user_id.encode("utf-8"), event))
    except asyncio.QueueFull:
        stats.dropped += 1
        return False
    return True


async def flush() -> None:
    """Wait until every queued event has reached the producer.

    Only returns once the publisher is connected; tests use it to observe
    what was published.
    """
    if _queue is not None:
        await _queue.join()


async def shutdown() -> None:
    """Flush queued events and stop the producer, within bounded time."""
    global _producer, _queue, _task
    task, queue = _task, _queue
    _task = _queue = None  # log_request() refuses events from here on

    if task is not None:
        if _producer is not None and not task.done():
            try:
                await asyncio.wait_for(queue.join(), SHUTDOWN_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                pass
        stats.dropped += queue.qsize()
        task.cancel()
        await asyncio.wait([task])

    producer, _producer = _producer, None
    if producer is not None:
        # stop() also flushes what the producer itself has buffered.
        await _stop_quietly(producer)
