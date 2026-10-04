"""Kafka -> ClickHouse ingestion for gateway usage events.

The gateway publishes one JSON event per request, on one topic for served
requests and another for rate-limit rejections. This service batches both
into ``api_usage`` in ClickHouse, which the dashboard queries.

Delivery is at-least-once. Offsets are committed only after a batch is
written, so a crash between the two replays the batch rather than losing
it. A replay can duplicate rows; for traffic analytics that is the right
side to err on.

A batch is written when it is full or when its oldest event has waited
FLUSH_INTERVAL seconds, whichever comes first. Without the time bound a
quiet system would hold events in memory until the thousandth arrived, and
the dashboard would show nothing.
"""
import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional, Sequence, Tuple

from aiokafka import AIOKafkaConsumer
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import KafkaError, TopicAlreadyExistsError
from tenacity import retry, stop_after_attempt, wait_fixed

from aggregator.setup_clickhouse import DATABASE, connect, ensure_schema_when_ready

logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPICS = (
    os.getenv("API_REQUESTS_TOPIC", "api-requests"),
    os.getenv("RATE_LIMITED_TOPIC", "rate-limited-events"),
)
GROUP_ID = os.getenv("KAFKA_GROUP_ID", "analytics-aggregator")
TOPIC_PARTITIONS = int(os.getenv("KAFKA_TOPIC_PARTITIONS", "3"))
TOPIC_REPLICATION = int(os.getenv("KAFKA_TOPIC_REPLICATION", "1"))

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1000"))
FLUSH_INTERVAL = float(os.getenv("FLUSH_INTERVAL_SECONDS", "2"))
WRITE_ATTEMPTS = 5

# (epoch seconds, user_id, endpoint, status_code, response_time_ms)
Row = Tuple[int, str, str, int, int]
Writer = Callable[[List[Row]], Awaitable[None]]

_WRITE_ERRORS = (ClickHouseError, OSError, EOFError)


def parse_event(raw: Optional[bytes]) -> Optional[Row]:
    """Turn one Kafka message into a table row, or None if it is unusable.

    A malformed event is logged and skipped. Raising instead would stop the
    consumer on the same poison message forever.
    """
    try:
        event = json.loads(raw)
        timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return (
            # An integer is unambiguous; a naive datetime would be read in
            # whatever timezone the server happens to run in.
            int(timestamp.timestamp()),
            str(event["user_id"]),
            str(event["endpoint"]),
            int(event["status_code"]),
            max(0, int(event["response_time"])),
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        logger.warning("Skipping malformed event: %r", raw[:200] if raw else raw)
        return None


def insert_rows(client: Client, rows: Sequence[Row]) -> None:
    client.execute(
        f"INSERT INTO {DATABASE}.api_usage "
        "(timestamp, user_id, endpoint, status_code, response_time) VALUES",
        list(rows),
    )


async def write_with_retry(
    write: Writer, rows: List[Row], attempts: int = WRITE_ATTEMPTS, sleep=asyncio.sleep
) -> None:
    """Write a batch, backing off on failure; re-raise once out of attempts.

    Giving up ends the process. Its offsets were never committed, so the
    restarted consumer re-reads the batch: Kafka is the buffer, not memory.
    """
    for attempt in range(1, attempts + 1):
        try:
            await write(rows)
            return
        except _WRITE_ERRORS:
            if attempt == attempts:
                raise
            delay = 2 ** (attempt - 1)
            logger.warning(
                "Writing %d rows failed (attempt %d/%d); retrying in %ss",
                len(rows), attempt, attempts, delay, exc_info=True,
            )
            await sleep(delay)


async def run(
    consumer,
    write: Writer,
    *,
    batch_size: int = BATCH_SIZE,
    flush_interval: float = FLUSH_INTERVAL,
    stop: Optional[asyncio.Event] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep=asyncio.sleep,
) -> None:
    """Consume, batch and write until ``stop`` is set, then flush and return."""
    rows: List[Row] = []
    consumed = 0
    oldest: Optional[float] = None

    async def flush() -> None:
        nonlocal rows, consumed, oldest
        if rows:
            await write_with_retry(write, rows, sleep=sleep)
        # Malformed messages still advance the offset, or they would be
        # re-read and skipped again after every restart.
        await consumer.commit()
        logger.info("Wrote %d rows from %d events", len(rows), consumed)
        rows, consumed, oldest = [], 0, None

    while stop is None or not stop.is_set():
        # Never block longer than the flush interval, or a quiet topic would
        # delay writing the events already buffered.
        records = await consumer.getmany(
            timeout_ms=max(100, int(flush_interval * 1000)), max_records=batch_size
        )
        for messages in records.values():
            for message in messages:
                if oldest is None:
                    oldest = clock()
                consumed += 1
                row = parse_event(message.value)
                if row is not None:
                    rows.append(row)

        if consumed and (consumed >= batch_size or clock() - oldest >= flush_interval):
            await flush()

    if consumed:
        await flush()


def ensure_topics(admin_factory=KafkaAdminClient) -> None:
    """Create the event topics if they are missing.

    A consumer that subscribes before its topic exists only notices it on a
    later metadata refresh, minutes away by default. Brokers that refuse
    topic creation (MSK with auto-create off, missing ACLs) are fine too, as
    long as the topics were provisioned; that is logged, not fatal. An
    unreachable broker is raised, so the caller can wait for it.
    """
    admin = admin_factory(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS, client_id="sentryflow-aggregator")
    try:
        existing = set(admin.list_topics())
        missing = [topic for topic in TOPICS if topic not in existing]
        if missing:
            admin.create_topics(
                [NewTopic(t, num_partitions=TOPIC_PARTITIONS, replication_factor=TOPIC_REPLICATION) for t in missing]
            )
            logger.info("Created topics %s", ", ".join(missing))
    except TopicAlreadyExistsError:
        pass  # another replica won the race
    except KafkaError:
        logger.warning("Could not create topics %s; assuming they are provisioned", TOPICS, exc_info=True)
    finally:
        admin.close()


@retry(stop=stop_after_attempt(30), wait=wait_fixed(2), reraise=True)
async def _start(consumer: AIOKafkaConsumer) -> None:
    """Start the consumer, retried while the broker is still coming up."""
    await consumer.start()


async def main() -> None:  # pragma: no cover - wiring, exercised by the compose stack
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    client = connect()
    await asyncio.to_thread(ensure_schema_when_ready, client)
    await asyncio.to_thread(retry(stop=stop_after_attempt(30), wait=wait_fixed(2), reraise=True)(ensure_topics))

    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=GROUP_ID,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await _start(consumer)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async def write(rows: List[Row]) -> None:
        # clickhouse-driver is blocking; keep it off the event loop so the
        # consumer's heartbeats are not starved during a slow insert.
        await asyncio.to_thread(insert_rows, client, rows)

    logger.info("Consuming %s from %s", ", ".join(TOPICS), KAFKA_BOOTSTRAP_SERVERS)
    try:
        await run(consumer, write, stop=stop)
    finally:
        await consumer.stop()
        client.disconnect()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
