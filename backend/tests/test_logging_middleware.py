"""Usage-event publishing to Kafka.

Requests only queue events; a background task connects to Kafka and
publishes them. These tests drive that task directly on the test's loop.
"""
import asyncio
import logging

import pytest
from aiokafka.errors import KafkaConnectionError, KafkaTimeoutError

from backend.config import settings
from backend.middlewares import logging_middleware
from backend.middlewares.logging_middleware import build_event, log_request


@pytest.fixture
async def publisher(fake_kafka):
    """The background publisher, running against the recording producer."""
    await logging_middleware.start_producer()
    yield fake_kafka
    await logging_middleware.shutdown()


async def published():
    await asyncio.wait_for(logging_middleware.flush(), 2)


def delivered(value=None):
    delivery = asyncio.get_running_loop().create_future()
    delivery.set_result(value)
    return delivery


def test_build_event_shape():
    event = build_event("user-1", "/api/v1/hello", 200, 42)
    assert event["user_id"] == "user-1"
    assert event["endpoint"] == "/api/v1/hello"
    assert event["status_code"] == 200
    assert event["response_time"] == 42
    assert event["timestamp"].endswith("+00:00"), "timestamps must be timezone-aware"


# --------------------------------------------------------------------------
# Queueing and publishing
# --------------------------------------------------------------------------

async def test_events_go_to_the_requests_topic(publisher):
    assert log_request("u1", "/x", 200, 10) is True
    await published()
    assert publisher.sent[0]["topic"] == settings.API_REQUESTS_TOPIC


async def test_throttled_events_go_to_the_rate_limited_topic(publisher):
    log_request("u1", "/x", 429, 0)
    await published()
    assert publisher.sent[0]["topic"] == settings.RATE_LIMITED_TOPIC


async def test_events_are_keyed_by_user_for_ordering(publisher):
    log_request("user-42", "/x", 200, 10)
    await published()
    assert publisher.sent[0]["key"] == b"user-42"


async def test_events_are_published_in_the_order_they_happened(publisher):
    for n in range(5):
        log_request("u1", f"/{n}", 200, n)
    await published()
    assert [m["value"]["endpoint"] for m in publisher.sent] == ["/0", "/1", "/2", "/3", "/4"]


def test_nothing_is_queued_before_the_publisher_starts():
    assert log_request("u1", "/x", 200, 10) is False


async def test_starting_twice_keeps_one_publisher(publisher):
    first = logging_middleware._task
    await logging_middleware.start_producer()
    assert logging_middleware._task is first


async def test_a_full_queue_drops_events_and_counts_them(fake_kafka, monkeypatch):
    """Kafka too slow or down: the queue absorbs a burst, then sheds load
    instead of holding requests or memory."""
    monkeypatch.setattr(settings, "USAGE_EVENT_BUFFER", 2)
    await logging_middleware.start_producer()
    try:
        # Nothing awaits in between, so the publisher has taken none of these.
        assert [log_request("u1", "/x", 200, 1) for _ in range(5)] == [True, True, False, False, False]
        assert logging_middleware.status()["queued"] == 2
        assert logging_middleware.status()["dropped"] == 3
    finally:
        await logging_middleware.shutdown()
    assert len(fake_kafka.sent) == 2


# --------------------------------------------------------------------------
# Failures
# --------------------------------------------------------------------------

async def test_send_errors_are_counted_and_publishing_continues(publisher):
    publisher.fail = True
    log_request("u1", "/lost", 200, 1)
    await published()
    publisher.fail = False
    log_request("u1", "/kept", 200, 1)
    await published()

    assert [m["value"]["endpoint"] for m in publisher.sent] == ["/kept"]
    assert logging_middleware.status()["failed"] == 1


async def test_lost_deliveries_are_counted_and_logged_once(fake_kafka, caplog):
    """How an outage after start-up looks: send() succeeds, delivery fails later."""
    deliveries = []

    async def send(topic, value, key=None):
        deliveries.append(asyncio.get_running_loop().create_future())
        return deliveries[-1]

    fake_kafka.send = send
    await logging_middleware.start_producer()
    try:
        for _ in range(3):
            log_request("u1", "/x", 200, 1)
        await published()
        with caplog.at_level(logging.WARNING, logger=logging_middleware.__name__):
            for delivery in deliveries:
                delivery.set_exception(KafkaTimeoutError())
            await asyncio.sleep(0)

        assert logging_middleware.status()["failed"] == 3
        assert logging_middleware.status()["delivering"] is False
        assert len([r for r in caplog.records if "not accepting" in r.getMessage()]) == 1

        log_request("u1", "/x", 200, 1)
        await published()
        deliveries[-1].set_result(None)
        await asyncio.sleep(0)
        assert logging_middleware.status()["delivering"] is True
    finally:
        await logging_middleware.shutdown()


# --------------------------------------------------------------------------
# Connecting
# --------------------------------------------------------------------------

class FlakyBroker:
    """A producer double for Kafka that is down for the first ``down_for`` attempts."""

    attempts = []

    def __init__(self, down_for):
        self.down_for = down_for
        self.sent = []
        self.stopped = False
        FlakyBroker.attempts.append(self)

    async def start(self):
        if len(FlakyBroker.attempts) <= self.down_for:
            raise KafkaConnectionError("Unable to bootstrap from [('kafka', 9092)]")

    async def send(self, topic, value, key=None):
        self.sent.append(value)
        return delivered()

    async def stop(self):
        self.stopped = True


async def test_the_publisher_connects_once_kafka_arrives(monkeypatch):
    """Kafka down at boot: keep retrying, rather than log nothing until a restart."""
    logging_middleware.set_producer(None)
    monkeypatch.setattr(logging_middleware, "RETRY_INITIAL_SECONDS", 0.01)
    monkeypatch.setattr(FlakyBroker, "attempts", [])
    monkeypatch.setattr(logging_middleware, "_new_producer", lambda: FlakyBroker(down_for=2))

    await logging_middleware.start_producer()
    try:
        assert logging_middleware.status()["connected"] is False
        # Queued while Kafka is still down, published once it is up.
        log_request("u1", "/early", 200, 1)
        await published()

        failed, connected = FlakyBroker.attempts[:2], FlakyBroker.attempts[2]
        assert len(FlakyBroker.attempts) == 3
        assert all(attempt.stopped for attempt in failed), "failed attempts must release their client"
        assert connected.sent[0]["endpoint"] == "/early"
        assert logging_middleware.status()["connected"] is True
    finally:
        await logging_middleware.shutdown()
    assert connected.stopped


def test_retry_backoff_doubles_up_to_a_cap():
    assert [logging_middleware.backoff(n) for n in range(7)] == [1, 2, 4, 8, 16, 30, 30]


async def test_a_publisher_crash_is_logged(monkeypatch, caplog):
    logging_middleware.set_producer(None)

    def misconfigured():
        raise ValueError("bootstrap_servers must be a string")

    monkeypatch.setattr(logging_middleware, "_new_producer", misconfigured)
    await logging_middleware.start_producer()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert "usage logging is off" in caplog.text
    await logging_middleware.shutdown()


# --------------------------------------------------------------------------
# Shutdown
# --------------------------------------------------------------------------

async def test_shutdown_publishes_what_is_queued_then_stops(fake_kafka):
    await logging_middleware.start_producer()
    for n in range(3):
        log_request("u1", f"/{n}", 200, 1)

    await logging_middleware.shutdown()

    assert len(fake_kafka.sent) == 3
    assert fake_kafka.stopped
    assert logging_middleware.get_producer() is None
    assert log_request("u1", "/late", 200, 1) is False


async def test_shutdown_is_bounded_when_kafka_hangs(fake_kafka, monkeypatch):
    monkeypatch.setattr(logging_middleware, "SHUTDOWN_TIMEOUT_SECONDS", 0.05)
    fake_kafka.stall = 60
    await logging_middleware.start_producer()
    for _ in range(3):
        log_request("u1", "/x", 200, 1)

    await asyncio.wait_for(logging_middleware.shutdown(), 2)

    # One event was stuck in send() and two never left the queue.
    assert logging_middleware.status()["dropped"] == 3
    assert fake_kafka.sent == []


async def test_shutdown_while_connecting_closes_the_half_open_producer(monkeypatch):
    logging_middleware.set_producer(None)
    connecting = asyncio.Event()

    class Unanswered:
        stopped = False

        async def start(self):
            connecting.set()
            await asyncio.sleep(3600)  # a blackholed broker never answers

        async def stop(self):
            Unanswered.stopped = True

    monkeypatch.setattr(logging_middleware, "_new_producer", Unanswered)
    await logging_middleware.start_producer()
    await connecting.wait()

    await asyncio.wait_for(logging_middleware.shutdown(), 2)

    assert Unanswered.stopped
