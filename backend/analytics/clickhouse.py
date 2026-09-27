"""ClickHouse access for the dashboard's analytics endpoints.

clickhouse-driver speaks the native protocol and is synchronous, and one
client must not be shared between threads. Queries therefore run in the
threadpool, and each worker thread keeps its own lazily opened connection:
a busy dashboard reuses connections, and two requests never interleave on
one socket.
"""
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError
from fastapi.concurrency import run_in_threadpool

from backend.config import settings

logger = logging.getLogger(__name__)

Rows = List[tuple]
Executor = Callable[[str, str, Dict[str, Any]], Rows]


class AnalyticsUnavailable(Exception):
    """ClickHouse could not answer. The API maps this to 503."""


_local = threading.local()
# Every client ever opened, so shutdown can close connections that live in
# other threads' thread-locals.
_clients: List[Client] = []
_clients_lock = threading.Lock()

# Test seam: when set, queries go here instead of to ClickHouse.
_executor: Optional[Executor] = None


def _new_client() -> Client:
    return Client(
        host=settings.CLICKHOUSE_HOST,
        port=settings.CLICKHOUSE_PORT,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
        connect_timeout=3,
        send_receive_timeout=settings.ANALYTICS_QUERY_TIMEOUT + 5,
        settings={
            # Enforced server-side, so a runaway query is cancelled rather
            # than left running after the HTTP request gives up on it.
            "max_execution_time": settings.ANALYTICS_QUERY_TIMEOUT,
            # Reads only. The queries are parameterised; this is the second
            # line of defence.
            "readonly": 2,
        },
    )


def _client() -> Client:
    client = getattr(_local, "client", None)
    if client is None:
        client = _new_client()
        _local.client = client
        with _clients_lock:
            _clients.append(client)
    return client


def _execute(sql: str, params: Dict[str, Any]) -> Rows:
    try:
        return _client().execute(sql, params)
    except (ClickHouseError, OSError, EOFError) as exc:
        # After a network error the connection may be half-open. Drop it so
        # the next query on this thread starts clean.
        client = getattr(_local, "client", None)
        if client is not None:
            client.disconnect()
        raise AnalyticsUnavailable(str(exc)) from exc


async def query(name: str, sql: str, params: Dict[str, Any]) -> Rows:
    """Run one read query and return its rows.

    ``name`` labels the query in logs, and lets tests route canned results
    without matching on SQL text.
    """
    if _executor is not None:
        return _executor(name, sql, params)
    try:
        return await run_in_threadpool(_execute, sql, params)
    except AnalyticsUnavailable:
        logger.warning("Analytics query %s failed", name, exc_info=True)
        raise


def set_executor(executor: Optional[Executor]) -> None:
    """Route queries to ``executor`` instead of ClickHouse. For tests."""
    global _executor
    _executor = executor


def close_all() -> None:
    """Close every connection. Called on application shutdown."""
    with _clients_lock:
        for client in _clients:
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001 - never fail a shutdown
                logger.warning("Error closing a ClickHouse connection", exc_info=True)
        _clients.clear()
