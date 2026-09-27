"""Database work stays off the event loop, on every route that does any.

Each process serves all of its requests from one event loop. A synchronous
database call made on it stalls every request in flight, gateway traffic
included, for the length of the round trip. So queries run in the
threadpool: plain ``def`` routes and dependencies run there already, and
async ones hand their queries to it explicitly.

These tests record every SQL statement executed while an event loop is
running on the current thread, and drive each route that touches the
database.
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from backend.models import database

NOW = 1_727_190_000


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


@pytest.fixture
def queries_on_loop():
    """SQL statements executed on the event loop, as they happen."""
    seen = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if _on_event_loop():
            seen.append(statement)

    event.listen(database.engine, "before_cursor_execute", record)
    yield seen
    event.remove(database.engine, "before_cursor_execute", record)


@pytest.fixture
def accounts(client, user, admin, api_key, fake_clickhouse):
    """A user with a key and a rate-limit rule, and analytics that name them."""
    fake_clickhouse.results["throttled_by_user"] = [(user["id"], 10, 5)]
    fake_clickhouse.results["logs"] = [(NOW, user["id"], "/api/v1/hello", 200, 3)]
    fake_clickhouse.results["top_users"] = [(user["id"], 10, 0, 0, 1.0, NOW)]
    rule = client.put("/limits", headers=admin["headers"], json=_rule(user["id"])).json()
    return SimpleNamespace(user=user, admin=admin, api_key=api_key, rule=rule)


def _rule(user_id):
    return {
        "user_id": user_id,
        "endpoint": "*",
        "requests_per_minute": 30,
        "burst_capacity": 5,
        "algorithm": "sliding_window",
    }


ROUTES = {
    # The gateway path and the probes
    "GET /api/v1/hello": lambda a: ("GET", "/api/v1/hello", {"headers": {"x-api-key": a.api_key["key"]}}),
    "GET /health/ready": lambda a: ("GET", "/health/ready", {}),
    # Accounts and keys
    "POST /auth/signup": lambda a: (
        "POST",
        "/auth/signup",
        {"json": {"username": "newcomer", "email": "newcomer@example.com", "password": "pw-123456"}},
    ),
    "POST /auth/login": lambda a: (
        "POST",
        "/auth/login",
        {"data": {"username": a.user["username"], "password": a.user["password"]}},
    ),
    "POST /auth/refresh": lambda a: ("POST", "/auth/refresh", {"json": {"refresh_token": a.user["refresh_token"]}}),
    "GET /auth/me": lambda a: ("GET", "/auth/me", {"headers": a.user["headers"]}),
    "GET /auth/users": lambda a: ("GET", "/auth/users?search=test", {"headers": a.admin["headers"]}),
    "GET /auth/apikeys": lambda a: ("GET", "/auth/apikeys", {"headers": a.user["headers"]}),
    "POST /auth/apikeys/create": lambda a: (
        "POST",
        "/auth/apikeys/create",
        {"headers": a.user["headers"], "json": {"name": "another"}},
    ),
    "DELETE /auth/apikeys/{id}": lambda a: (
        "DELETE",
        f"/auth/apikeys/{a.api_key['id']}",
        {"headers": a.user["headers"]},
    ),
    # Rate-limit rules
    "GET /limits": lambda a: ("GET", "/limits", {"headers": a.admin["headers"]}),
    "PUT /limits": lambda a: ("PUT", "/limits", {"headers": a.admin["headers"], "json": _rule(a.user["id"])}),
    "DELETE /limits/{id}": lambda a: ("DELETE", f"/limits/{a.rule['id']}", {"headers": a.admin["headers"]}),
    # Analytics, which look usernames up in the database
    "GET /analytics/usage": lambda a: (
        "GET",
        f"/analytics/usage?user_id={a.user['id']}",
        {"headers": a.admin["headers"]},
    ),
    "GET /analytics/rate-limits": lambda a: ("GET", "/analytics/rate-limits", {"headers": a.admin["headers"]}),
    "GET /analytics/logs": lambda a: ("GET", "/analytics/logs", {"headers": a.admin["headers"]}),
    "GET /analytics/users": lambda a: ("GET", "/analytics/users", {"headers": a.admin["headers"]}),
}


@pytest.mark.parametrize("route", ROUTES)
def test_database_work_stays_off_the_event_loop(route, client, accounts, queries_on_loop):
    method, path, kwargs = ROUTES[route](accounts)

    response = client.request(method, path, **kwargs)

    assert response.status_code < 400, response.text
    assert queries_on_loop == [], f"{route} queried the database on the event loop"
