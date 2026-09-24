"""Usage-event production to Kafka."""
from backend.config import settings
from backend.middlewares import logging_middleware
from backend.middlewares.logging_middleware import build_event, log_request


def test_build_event_shape():
    event = build_event("user-1", "/api/v1/hello", 200, 42)
    assert event["user_id"] == "user-1"
    assert event["endpoint"] == "/api/v1/hello"
    assert event["status_code"] == 200
    assert event["response_time"] == 42
    assert event["timestamp"].endswith("+00:00"), "timestamps must be timezone-aware"


async def test_log_request_publishes_to_the_requests_topic(fake_kafka):
    assert await log_request("u1", "/x", 200, 10) is True
    assert fake_kafka.sent[0]["topic"] == settings.API_REQUESTS_TOPIC


async def test_throttled_events_go_to_the_rate_limited_topic(fake_kafka):
    await log_request("u1", "/x", 429, 0)
    assert fake_kafka.sent[0]["topic"] == settings.RATE_LIMITED_TOPIC


async def test_log_request_is_a_no_op_without_a_producer():
    logging_middleware.set_producer(None)
    assert await log_request("u1", "/x", 200, 10) is False


async def test_producer_errors_are_swallowed(fake_kafka):
    """A logging failure must never turn a good request into an error."""
    fake_kafka.fail = True
    assert await log_request("u1", "/x", 200, 10) is False


async def test_events_are_keyed_by_user_for_ordering(fake_kafka):
    await log_request("user-42", "/x", 200, 10)
    assert fake_kafka.sent[0]["key"] == b"user-42"


async def test_start_producer_tolerates_an_unreachable_broker(monkeypatch):
    """Booting without Kafka is allowed; the gateway still serves traffic."""
    logging_middleware.set_producer(None)

    class Unreachable:
        def __init__(self, *a, **k):
            pass

        async def start(self):
            raise OSError("no broker")

    monkeypatch.setattr(logging_middleware, "AIOKafkaProducer", Unreachable)

    assert await logging_middleware.start_producer() is None
    assert logging_middleware.get_producer() is None


async def test_start_producer_is_idempotent(fake_kafka):
    """Concurrent first requests must not each build a producer."""
    assert await logging_middleware.start_producer() is fake_kafka


async def test_shutdown_clears_the_producer(fake_kafka):
    await logging_middleware.shutdown()
    assert logging_middleware.get_producer() is None
