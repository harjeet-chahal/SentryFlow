"""Aggregator: event parsing, batching, commit ordering and failure handling.

Kafka and ClickHouse are replaced by scripted doubles, and time by a clock
the test advances, so every flush decision is deterministic.
"""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from clickhouse_driver.errors import NetworkError
from kafka.errors import KafkaError, NoBrokersAvailable, TopicAlreadyExistsError

from aggregator import batch_consumer, setup_clickhouse
from aggregator.batch_consumer import parse_event, run, write_with_retry

T0 = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def event(status=200, response_time=3, **overrides):
    body = {
        "timestamp": T0.isoformat(),
        "user_id": "u1",
        "endpoint": "/api/v1/hello",
        "status_code": status,
        "response_time": response_time,
        **overrides,
    }
    return json.dumps(body).encode()


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def test_an_event_becomes_a_row():
    assert parse_event(event()) == (int(T0.timestamp()), "u1", "/api/v1/hello", 200, 3)


def test_zulu_and_naive_timestamps_are_utc():
    zulu = parse_event(event(timestamp="2026-09-24T12:00:00Z"))
    naive = parse_event(event(timestamp="2026-09-24T12:00:00"))
    assert zulu[0] == naive[0] == int(T0.timestamp())


def test_negative_response_times_are_clamped():
    assert parse_event(event(response_time=-5))[4] == 0


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[]",
        json.dumps({"timestamp": T0.isoformat()}).encode(),
        event(timestamp="yesterday"),
        event(status="teapot"),
        None,
    ],
)
def test_malformed_events_are_skipped_not_raised(raw):
    assert parse_event(raw) is None


# --------------------------------------------------------------------------
# Batching
# --------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ScriptedConsumer:
    """Replays polls; each poll may advance the clock or end the run."""

    def __init__(self, clock, stop, polls):
        self.clock, self.stop, self.polls = clock, stop, list(polls)
        self.commits = 0
        self.log = []

    async def getmany(self, timeout_ms, max_records):
        if not self.polls:
            self.stop.set()
            return {}
        values, advance = self.polls.pop(0)
        self.clock.now += advance
        messages = [SimpleNamespace(value=v) for v in values]
        return {"partition-0": messages} if messages else {}

    async def commit(self):
        self.commits += 1
        self.log.append("commit")


class RecordingWriter:
    def __init__(self, consumer, failures=0):
        self.consumer, self.failures = consumer, failures
        self.batches = []

    async def __call__(self, rows):
        if self.failures:
            self.failures -= 1
            raise NetworkError("ClickHouse down")
        self.batches.append(list(rows))
        self.consumer.log.append(f"write:{len(rows)}")


async def no_sleep(_seconds):
    return None


def harness(polls, failures=0):
    clock, stop = Clock(), asyncio.Event()
    consumer = ScriptedConsumer(clock, stop, polls)
    writer = RecordingWriter(consumer, failures)
    return consumer, writer, dict(stop=stop, clock=clock, sleep=no_sleep)


async def test_a_full_batch_is_written_straight_away():
    consumer, writer, opts = harness([([event()] * 3, 0)])

    await run(consumer, writer, batch_size=3, flush_interval=60, **opts)

    assert [len(b) for b in writer.batches] == [3]


async def test_a_quiet_topic_still_flushes_on_time():
    """The bug this replaces: small batches waited for the thousandth event."""
    consumer, writer, opts = harness([([event()], 0), ([], 1.0), ([], 1.5)])

    await run(consumer, writer, batch_size=1000, flush_interval=2, **opts)

    assert [len(b) for b in writer.batches] == [1]
    # Written by the time-based flush, before the run ended.
    assert consumer.log == ["write:1", "commit"]


async def test_nothing_is_written_before_the_batch_is_due():
    consumer, writer, opts = harness([([event()], 0), ([], 0.5)])
    opts["stop"].set()  # stop before the first poll would be processed

    await run(consumer, writer, batch_size=10, flush_interval=2, **opts)

    assert writer.batches == []
    assert consumer.commits == 0


async def test_offsets_are_committed_only_after_the_write():
    consumer, writer, opts = harness([([event()] * 2, 0)])

    await run(consumer, writer, batch_size=2, flush_interval=60, **opts)

    assert consumer.log == ["write:2", "commit"]


async def test_malformed_events_still_advance_the_offset():
    consumer, writer, opts = harness([([b"garbage", b"junk"], 0)])

    await run(consumer, writer, batch_size=2, flush_interval=60, **opts)

    assert writer.batches == []
    assert consumer.commits == 1


async def test_stopping_flushes_what_is_buffered():
    consumer, writer, opts = harness([([event()], 0)])

    await run(consumer, writer, batch_size=100, flush_interval=60, **opts)

    assert [len(b) for b in writer.batches] == [1]
    assert consumer.commits == 1


async def test_a_failed_write_is_retried_before_committing():
    consumer, writer, opts = harness([([event()] * 2, 0)], failures=2)

    await run(consumer, writer, batch_size=2, flush_interval=60, **opts)

    assert [len(b) for b in writer.batches] == [2]
    assert consumer.log == ["write:2", "commit"]


async def test_giving_up_leaves_the_offsets_uncommitted():
    """The restarted consumer re-reads the batch; nothing is lost."""
    consumer, writer, opts = harness([([event()], 0)], failures=99)

    with pytest.raises(NetworkError):
        await run(consumer, writer, batch_size=1, flush_interval=60, **opts)

    assert consumer.commits == 0


async def test_retry_backs_off_exponentially():
    delays = []

    async def record(seconds):
        delays.append(seconds)

    attempts = {"n": 0}

    async def flaky(rows):
        attempts["n"] += 1
        if attempts["n"] < 4:
            raise OSError("reset")

    await write_with_retry(flaky, [("row",)], attempts=5, sleep=record)
    assert delays == [1, 2, 4]


# --------------------------------------------------------------------------
# ClickHouse writes and schema
# --------------------------------------------------------------------------

class RecordingClickHouse:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))


def test_rows_are_inserted_into_the_events_table():
    client = RecordingClickHouse()
    row = parse_event(event())

    batch_consumer.insert_rows(client, [row])

    sql, params = client.statements[0]
    assert sql.startswith(f"INSERT INTO {setup_clickhouse.DATABASE}.api_usage")
    assert params == [row]


def test_schema_creates_the_database_and_table():
    client = RecordingClickHouse()

    setup_clickhouse.ensure_schema(client, database="analytics", retention_days=30)

    statements = [sql for sql, _ in client.statements]
    assert statements[0] == "CREATE DATABASE IF NOT EXISTS analytics"
    assert "CREATE TABLE IF NOT EXISTS analytics.api_usage" in statements[1]
    assert "TTL timestamp + INTERVAL 30 DAY" in statements[1]


@pytest.mark.parametrize("name", ["sentry-flow", "db; DROP TABLE x", "1abc", ""])
def test_schema_refuses_an_unsafe_database_name(name):
    with pytest.raises(ValueError):
        setup_clickhouse.ensure_schema(RecordingClickHouse(), database=name)


def test_schema_setup_waits_for_clickhouse_to_start(monkeypatch):
    calls = {"n": 0}

    def flaky(client):
        calls["n"] += 1
        if calls["n"] < 3:
            raise NetworkError("starting up")

    monkeypatch.setattr(setup_clickhouse, "ensure_schema", flaky)
    # Skip the real two-second waits between attempts.
    monkeypatch.setattr(setup_clickhouse.ensure_schema_when_ready.retry, "sleep", lambda _s: None)

    setup_clickhouse.ensure_schema_when_ready(RecordingClickHouse())
    assert calls["n"] == 3


def test_connect_targets_no_database(monkeypatch):
    captured = {}
    monkeypatch.setattr(setup_clickhouse, "Client", lambda **kwargs: captured.update(kwargs))

    setup_clickhouse.connect()

    assert "database" not in captured
    assert captured["host"] == setup_clickhouse.CLICKHOUSE_HOST


# --------------------------------------------------------------------------
# Topics
# --------------------------------------------------------------------------

class FakeAdmin:
    def __init__(self, existing=(), create_error=None):
        self.existing, self.create_error = list(existing), create_error
        self.created, self.closed = [], False

    def __call__(self, **kwargs):  # stands in for the KafkaAdminClient class
        return self

    def list_topics(self):
        return self.existing

    def create_topics(self, new_topics):
        if self.create_error:
            raise self.create_error
        self.created.extend(t.name for t in new_topics)

    def close(self):
        self.closed = True


def test_missing_topics_are_created():
    admin = FakeAdmin(existing=["api-requests"])
    batch_consumer.ensure_topics(admin)
    assert admin.created == ["rate-limited-events"]
    assert admin.closed


def test_existing_topics_are_left_alone():
    admin = FakeAdmin(existing=list(batch_consumer.TOPICS))
    batch_consumer.ensure_topics(admin)
    assert admin.created == []


@pytest.mark.parametrize("error", [TopicAlreadyExistsError(), KafkaError("not authorised")])
def test_topic_creation_problems_are_not_fatal(error):
    admin = FakeAdmin(create_error=error)
    batch_consumer.ensure_topics(admin)
    assert admin.closed


def test_an_unreachable_broker_is_raised_so_startup_can_wait():
    def unreachable(**kwargs):
        raise NoBrokersAvailable()

    with pytest.raises(NoBrokersAvailable):
        batch_consumer.ensure_topics(unreachable)


async def test_consumer_start_is_retried_while_kafka_boots(monkeypatch):
    class Consumer:
        attempts = 0

        async def start(self):
            Consumer.attempts += 1
            if Consumer.attempts < 3:
                raise KafkaError("not ready")

    monkeypatch.setattr(batch_consumer._start.retry, "sleep", no_sleep)
    await batch_consumer._start(Consumer())
    assert Consumer.attempts == 3
