"""Shared test fixtures.

The gateway depends on Postgres, Redis, Kafka and ClickHouse. Tests
substitute all four with in-process equivalents so the suite runs with no
services:

    Postgres   -> a per-test SQLite file
    Redis      -> fakeredis, which executes the real Lua scripts rather than
                  stubbing them, so the limiter logic is genuinely covered
    Kafka      -> a recording double that captures produced events
    ClickHouse -> a double that returns canned rows per named query. The SQL
                  itself is exercised against a real ClickHouse by
                  tests/integration, which CI runs with a service container.

These are set before any ``backend`` import, because configuration is read
from the environment at module import time.
"""
import asyncio
import os
import tempfile

# Must precede every backend import: backend.config snapshots the environment.
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="sentryflow-tests-"), "test.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_DB}")
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-in-production")
os.environ.setdefault("ENVIRONMENT", "test")

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import redis_client  # noqa: E402
from backend.analytics import clickhouse  # noqa: E402
from backend.analytics.clickhouse import AnalyticsUnavailable  # noqa: E402
from backend.limiter import rate_limiter  # noqa: E402
from backend.middlewares import logging_middleware  # noqa: E402
from backend.models import database, models  # noqa: E402


class RecordingProducer:
    """Stands in for AIOKafkaProducer, capturing what would be published."""

    def __init__(self, fail: bool = False):
        self.sent = []
        self.fail = fail
        # Seconds send() waits first, as aiokafka's does for buffer space
        # when the broker is down.
        self.stall = 0.0
        self.stopped = False

    async def send(self, topic, value, key=None):
        if self.stall:
            await asyncio.sleep(self.stall)
        if self.fail:
            raise OSError("broker unreachable")
        self.sent.append({"topic": topic, "value": value, "key": key})
        # Like aiokafka, send() only buffers; this future settles on delivery.
        delivery = asyncio.get_running_loop().create_future()
        delivery.set_result(None)
        return delivery

    async def stop(self):
        self.stopped = True

    def events_on(self, topic):
        return [m["value"] for m in self.sent if m["topic"] == topic]


class FakeClickHouse:
    """Stands in for ClickHouse: canned rows per named query, calls recorded."""

    def __init__(self):
        self.results = {}
        self.calls = []
        self.down = False

    def __call__(self, name, sql, params):
        if self.down:
            raise AnalyticsUnavailable("connection refused")
        self.calls.append({"name": name, "sql": sql, "params": params})
        return self.results.get(name, [])

    def call(self, name):
        matches = [c for c in self.calls if c["name"] == name]
        assert matches, f"query {name!r} was not run; ran {[c['name'] for c in self.calls]}"
        return matches[-1]

    def names(self):
        return [c["name"] for c in self.calls]


@pytest.fixture(autouse=True)
def clean_database():
    """Give every test an empty schema, so ordering cannot leak state."""
    models.Base.metadata.drop_all(bind=database.engine)
    models.Base.metadata.create_all(bind=database.engine)
    yield
    models.Base.metadata.drop_all(bind=database.engine)


@pytest.fixture(autouse=True)
def fake_redis():
    """Swap in fakeredis for the process-wide client."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.set_redis(client)
    # Lua scripts are bound to a client, so they must rebind to this one.
    rate_limiter.reset_scripts()
    yield client
    redis_client.reset_redis()
    rate_limiter.reset_scripts()


@pytest.fixture(autouse=True)
def fake_kafka():
    """Capture produced events instead of reaching a broker."""
    producer = RecordingProducer()
    logging_middleware.reset()
    logging_middleware.set_producer(producer)
    yield producer
    logging_middleware.reset()


@pytest.fixture(autouse=True)
def fake_clickhouse():
    """Answer analytics queries from canned rows; never reach a real server."""
    fake = FakeClickHouse()
    clickhouse.set_executor(fake)
    yield fake
    clickhouse.set_executor(None)


@pytest.fixture
def app():
    from backend.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def client(app):
    """A TestClient used as a context manager.

    This matters: entering the context keeps a single event loop for the
    whole test. Without it Starlette spins up a fresh loop per request, and
    the async Redis pool -- bound to the loop it was first used on -- raises
    on the second request.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def published(client, fake_kafka):
    """What reached Kafka, once the background publisher has caught up.

    Requests only queue their events, so read them through this rather than
    from ``fake_kafka`` straight after a request.
    """

    def _published():
        client.portal.call(logging_middleware.flush)
        return fake_kafka

    return _published


@pytest.fixture
def user_factory(client):
    """Register a user and return its credentials plus a bearer token."""

    def _make(username="tester", email=None, password="correct-horse-battery"):
        email = email or f"{username}@example.com"
        signup = client.post(
            "/auth/signup",
            json={"username": username, "email": email, "password": password},
        )
        assert signup.status_code == 201, signup.text

        login = client.post(
            "/auth/login", data={"username": username, "password": password}
        )
        assert login.status_code == 200, login.text
        tokens = login.json()
        return {
            "id": signup.json()["id"],
            "username": username,
            "email": email,
            "password": password,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "headers": {"Authorization": f"Bearer {tokens['access_token']}"},
        }

    return _make


@pytest.fixture
def user(user_factory):
    return user_factory()


@pytest.fixture
def admin(user_factory):
    """An operator account. Nobody can sign up as one, so grant it directly."""
    account = user_factory(username="operator")
    db = database.SessionLocal()
    try:
        db.query(models.User).filter(models.User.id == account["id"]).update({"is_admin": True})
        db.commit()
    finally:
        db.close()
    return account


@pytest.fixture
def api_key(client, user):
    """Create an API key for the default user and return the raw key."""
    response = client.post(
        "/auth/apikeys/create", json={"name": "test-key"}, headers=user["headers"]
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def gateway_headers_for(client):
    """Trade an API key for a gateway token; return headers that present it."""

    def _exchange(key):
        response = client.post("/auth/token", headers={"x-api-key": key})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _exchange


@pytest.fixture
def gateway_headers(gateway_headers_for, api_key):
    """Headers that authenticate the default user through the gateway."""
    return gateway_headers_for(api_key["key"])
