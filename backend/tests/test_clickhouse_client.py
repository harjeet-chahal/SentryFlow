"""The ClickHouse connection layer: one connection per thread, clean failure.

``clickhouse_driver.Client`` is replaced by a recording fake, so these run
without a server while still going through the real threadpool path.
"""
import threading

import pytest
from clickhouse_driver.errors import NetworkError

from backend.analytics import clickhouse
from backend.analytics.clickhouse import AnalyticsUnavailable
from backend.config import settings


class FakeClient:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.queries = []
        self.disconnects = 0
        self.fail_with = None
        FakeClient.instances.append(self)

    def execute(self, sql, params):
        if self.fail_with is not None:
            raise self.fail_with
        self.queries.append((sql, params))
        return [(1,)]

    def disconnect(self):
        self.disconnects += 1


@pytest.fixture
def driver(monkeypatch):
    """Route to the real execution path, with a fake driver underneath."""
    FakeClient.instances = []
    monkeypatch.setattr(clickhouse, "Client", FakeClient)
    monkeypatch.setattr(clickhouse, "_local", threading.local())
    monkeypatch.setattr(clickhouse, "_clients", [])
    clickhouse.set_executor(None)
    yield FakeClient
    clickhouse.close_all()


async def test_queries_run_through_the_driver(driver):
    rows = await clickhouse.query("probe", "SELECT %(x)s", {"x": 1})

    assert rows == [(1,)]
    assert driver.instances[0].queries == [("SELECT %(x)s", {"x": 1})]


def test_client_settings_come_from_configuration(driver):
    client = clickhouse._client()

    assert client.kwargs["host"] == settings.CLICKHOUSE_HOST
    assert client.kwargs["port"] == settings.CLICKHOUSE_PORT
    assert client.kwargs["database"] == settings.CLICKHOUSE_DATABASE
    # Enforced by the server: read-only, and bounded in time.
    assert client.kwargs["settings"]["readonly"] == 2
    assert client.kwargs["settings"]["max_execution_time"] == settings.ANALYTICS_QUERY_TIMEOUT


def test_a_thread_reuses_its_connection(driver):
    first = clickhouse._client()
    second = clickhouse._client()
    assert first is second
    assert len(driver.instances) == 1


def test_threads_never_share_a_connection(driver):
    seen = []
    worker = threading.Thread(target=lambda: seen.append(clickhouse._client()))
    worker.start()
    worker.join()

    assert seen[0] is not clickhouse._client()
    assert len(driver.instances) == 2


def test_driver_errors_become_analytics_unavailable(driver):
    client = clickhouse._client()
    client.fail_with = NetworkError("Connection refused")

    with pytest.raises(AnalyticsUnavailable):
        clickhouse._execute("SELECT 1", {})
    # The possibly half-open connection is dropped, not reused.
    assert client.disconnects == 1


@pytest.mark.parametrize("error", [OSError("reset"), EOFError()])
def test_socket_level_errors_are_handled_too(driver, error):
    clickhouse._client().fail_with = error
    with pytest.raises(AnalyticsUnavailable):
        clickhouse._execute("SELECT 1", {})


async def test_failures_surface_through_the_async_api(driver, monkeypatch):
    def unreachable():
        client = FakeClient()
        client.fail_with = NetworkError("Connection refused")
        return client

    # The query runs on a threadpool worker, which opens its own connection.
    monkeypatch.setattr(clickhouse, "_new_client", unreachable)
    with pytest.raises(AnalyticsUnavailable):
        await clickhouse.query("probe", "SELECT 1", {})


def test_close_all_disconnects_every_thread_s_client(driver):
    clickhouse._client()
    worker = threading.Thread(target=clickhouse._client)
    worker.start()
    worker.join()

    clickhouse.close_all()

    assert [c.disconnects for c in driver.instances] == [1, 1]
    assert clickhouse._clients == []


def test_close_all_never_raises(driver):
    client = clickhouse._client()

    def broken():
        raise RuntimeError("already gone")

    client.disconnect = broken
    clickhouse.close_all()  # must not raise


async def test_an_executor_replaces_the_server(driver):
    calls = []
    clickhouse.set_executor(lambda name, sql, params: calls.append(name) or [("canned",)])

    assert await clickhouse.query("named", "SELECT 1", {}) == [("canned",)]
    assert calls == ["named"]
    assert driver.instances == []
