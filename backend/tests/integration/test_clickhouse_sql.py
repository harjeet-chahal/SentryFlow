"""The analytics SQL, run against a real ClickHouse.

The unit suite replaces ClickHouse with canned rows, which proves what the
API does with results but not that the queries are right. These tests load
known events into a throwaway database, with the schema the aggregator
creates, and check every number the dashboard shows.

They run when CLICKHOUSE_TEST_HOST is set (CI uses a service container):

    CLICKHOUSE_TEST_HOST=localhost CLICKHOUSE_TEST_USER=sentryflow \\
    CLICKHOUSE_TEST_PASSWORD=sentryflow pytest tests/integration --no-cov
"""
import os
import threading
import time
import uuid

import pytest
from clickhouse_driver import Client

from aggregator.setup_clickhouse import ensure_schema
from backend.analytics import clickhouse, queries
from backend.config import settings

HOST = os.getenv("CLICKHOUSE_TEST_HOST")
pytestmark = pytest.mark.skipif(not HOST, reason="CLICKHOUSE_TEST_HOST not set")

PORT = int(os.getenv("CLICKHOUSE_TEST_PORT", "9000"))
USER = os.getenv("CLICKHOUSE_TEST_USER", "default")
PASSWORD = os.getenv("CLICKHOUSE_TEST_PASSWORD", "")


@pytest.fixture(scope="module")
def database():
    name = f"sentryflow_it_{uuid.uuid4().hex[:8]}"
    admin = Client(host=HOST, port=PORT, user=USER, password=PASSWORD)
    ensure_schema(admin, database=name)
    yield admin, name
    admin.execute(f"DROP DATABASE IF EXISTS {name}")
    admin.disconnect()


@pytest.fixture
def warehouse(database, monkeypatch):
    """Point the analytics layer at the throwaway database, for real."""
    admin, name = database
    admin.execute(f"TRUNCATE TABLE {name}.api_usage")

    monkeypatch.setattr(settings, "CLICKHOUSE_HOST", HOST)
    monkeypatch.setattr(settings, "CLICKHOUSE_PORT", PORT)
    monkeypatch.setattr(settings, "CLICKHOUSE_USER", USER)
    monkeypatch.setattr(settings, "CLICKHOUSE_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "CLICKHOUSE_DATABASE", name)
    monkeypatch.setattr(clickhouse, "_local", threading.local())
    monkeypatch.setattr(clickhouse, "_clients", [])
    clickhouse.set_executor(None)

    def load(*rows):
        admin.execute(
            f"INSERT INTO {name}.api_usage (timestamp, user_id, endpoint, status_code, response_time) VALUES",
            list(rows),
        )

    yield load
    clickhouse.close_all()


@pytest.fixture
def window():
    """The last 24 hourly buckets, ending with the current hour."""
    return queries.window_for("24h")


def at(window, bucket, second=0):
    """A timestamp inside one of the window's buckets (-1 is the current one)."""
    return window.bucket_starts[bucket] + second


def traffic(window):
    now_bucket, earlier = -1, -3
    return [
        # alice: four served, one error, two throttled, in the current hour
        (at(window, now_bucket, 1), "alice", "/api/v1/hello", 200, 10),
        (at(window, now_bucket, 2), "alice", "/api/v1/hello", 200, 20),
        (at(window, now_bucket, 3), "alice", "/api/v1/hello", 200, 30),
        (at(window, now_bucket, 4), "alice", "/api/v1/orders", 500, 40),
        (at(window, now_bucket, 5), "alice", "/api/v1/hello", 429, 1),
        (at(window, now_bucket, 6), "alice", "/api/v1/hello", 429, 1),
        # bob: two hours earlier
        (at(window, earlier, 1), "bob", "/api/v1/orders", 201, 50),
        (at(window, earlier, 2), "bob", "/api/v1/missing", 404, 5),
        # outside the window entirely
        (window.start - 3600, "alice", "/api/v1/hello", 200, 999),
    ]


async def test_summary_counts_and_percentiles(warehouse, window):
    warehouse(*traffic(window))

    summary = (await queries.usage(window, None))["summary"]

    assert summary["requests"] == 8
    assert summary["rate_limited"] == 2
    # 500 and 404 are errors; the 429s are not.
    assert summary["errors"] == 2
    assert summary["error_rate"] == 25.0
    # Latency is over the six served requests only: 10,20,30,40,50,5.
    assert summary["avg_ms"] == pytest.approx(25.8, abs=0.1)
    assert 5 <= summary["p50_ms"] <= 50
    assert summary["p99_ms"] <= 50


async def test_scoping_to_one_user(warehouse, window):
    warehouse(*traffic(window))

    summary = (await queries.usage(window, "bob"))["summary"]

    assert summary["requests"] == 2
    assert summary["rate_limited"] == 0


async def test_series_places_events_in_their_buckets(warehouse, window):
    warehouse(*traffic(window))

    series = (await queries.usage(window, None))["series"]

    assert len(series) == 24
    by_t = {point["t"]: point for point in series}
    current = by_t[window.bucket_starts[-1]]
    assert (current["requests"], current["rate_limited"], current["errors"]) == (6, 2, 1)
    assert by_t[window.bucket_starts[-3]]["requests"] == 2
    assert sum(point["requests"] for point in series) == 8
    # An empty bucket has no latency rather than zero latency.
    assert by_t[window.bucket_starts[0]]["p95_ms"] is None


async def test_status_mix_and_top_endpoints(warehouse, window):
    warehouse(*traffic(window))

    usage = await queries.usage(window, None)

    assert usage["status_codes"] == {"2xx": 4, "3xx": 0, "4xx": 3, "5xx": 1}
    top = usage["top_endpoints"]
    assert top[0]["endpoint"] == "/api/v1/hello"
    assert (top[0]["requests"], top[0]["rate_limited"]) == (5, 2)
    assert {row["endpoint"] for row in top} == {"/api/v1/hello", "/api/v1/orders", "/api/v1/missing"}


async def test_rate_limit_breakdowns(warehouse, window):
    warehouse(*traffic(window))

    data = await queries.rate_limits(window, None, include_users=True)

    assert data["totals"] == {"requests": 8, "rate_limited": 2, "rate_limited_rate": 25.0}
    assert data["by_endpoint"] == [{"endpoint": "/api/v1/hello", "requests": 5, "rate_limited": 2}]
    assert data["by_user"] == [{"user_id": "alice", "requests": 6, "rate_limited": 2}]


async def test_logs_filter_sort_and_truncate(warehouse, window):
    warehouse(*traffic(window))

    newest = await queries.logs(window, None, None, None, limit=3)
    assert newest["truncated"] is True
    assert [row["status_code"] for row in newest["rows"]] == [429, 429, 500]

    errors = await queries.logs(window, None, 5, None, limit=10)
    assert [row["endpoint"] for row in errors["rows"]] == ["/api/v1/orders"]

    by_path = await queries.logs(window, "bob", None, "ORDERS", limit=10)
    assert [(row["user_id"], row["status_code"]) for row in by_path["rows"]] == [("bob", 201)]
    assert by_path["truncated"] is False


async def test_per_user_breakdown(warehouse, window):
    warehouse(*traffic(window))

    stats = await queries.per_user(window)

    assert set(stats) == {"alice", "bob"}
    assert (stats["alice"]["requests"], stats["alice"]["rate_limited"]) == (6, 2)
    assert stats["bob"]["last_seen"] == at(window, -3, 2)


async def test_an_empty_window_yields_zeros_not_errors(warehouse, window):
    usage = await queries.usage(window, None)

    assert usage["summary"]["requests"] == 0
    assert usage["summary"]["p95_ms"] is None
    assert usage["top_endpoints"] == []


async def test_the_dashboard_connection_is_read_only(warehouse, database):
    _, name = database
    with pytest.raises(clickhouse.AnalyticsUnavailable):
        await clickhouse.query("write", f"INSERT INTO {name}.api_usage VALUES", {})


def test_the_events_table_has_a_retention_ttl(database):
    admin, name = database
    ddl = admin.execute(f"SHOW CREATE TABLE {name}.api_usage")[0][0]
    assert "TTL" in ddl


def test_timestamps_round_trip_as_utc(warehouse, database):
    admin, name = database
    moment = int(time.time()) // 60 * 60
    warehouse((moment, "tz", "/x", 200, 1))
    stored = admin.execute(f"SELECT toUnixTimestamp(timestamp) FROM {name}.api_usage WHERE user_id = 'tz'")
    assert stored == [(moment,)]
