"""Analytics endpoints: scoping, shaping and failure handling.

ClickHouse is replaced by a double that returns canned rows per named query
(see conftest). That covers everything the API does with the rows; the SQL
itself runs against a real ClickHouse in tests/integration.
"""
import math

import pytest

from backend.analytics import queries

NOW = 1_727_190_000  # 2024-09-24T15:00:00Z, a whole hour


class FrozenClock:
    """Replaces the ``time`` module inside queries, and nowhere else."""

    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now


# --------------------------------------------------------------------------
# Windows and buckets
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "range_key,step,buckets",
    [("1h", 60, 60), ("24h", 3600, 24), ("7d", 21600, 28), ("30d", 86400, 30)],
)
def test_each_range_has_a_fixed_bucket_layout(range_key, step, buckets):
    window = queries.window_for(range_key, now=NOW + 125)
    assert (window.step, window.buckets) == (step, buckets)
    assert len(window.bucket_starts) == buckets
    # Buckets are epoch-aligned, i.e. UTC minutes, hours and days.
    assert all(t % step == 0 for t in window.bucket_starts)


def test_window_ends_with_the_bucket_that_is_still_filling():
    window = queries.window_for("24h", now=NOW + 125)
    assert window.bucket_starts[-1] == NOW
    assert window.end == NOW + 3600
    assert window.start == NOW - 23 * 3600


def test_window_on_an_exact_boundary_starts_a_new_bucket():
    window = queries.window_for("1h", now=NOW)
    assert window.bucket_starts[-1] == NOW
    assert window.bucket_starts[0] == NOW - 59 * 60


def test_window_defaults_to_the_current_time():
    window = queries.window_for("1h")
    assert window.bucket_starts[-1] <= window.end


@pytest.mark.parametrize(
    "raw,expected", [(None, None), (float("nan"), None), (12.345, 12.3), (7, 7.0)]
)
def test_latency_values_are_rounded_and_nan_becomes_null(raw, expected):
    assert queries._ms(raw) == expected


def test_percentages_do_not_divide_by_zero():
    assert queries._percent(3, 0) == 0.0
    assert queries._percent(1, 3) == 33.33


# --------------------------------------------------------------------------
# /analytics/usage
# --------------------------------------------------------------------------

def _usage_rows(fake, window):
    first, last = window.bucket_starts[0], window.bucket_starts[-1]
    fake.results["summary"] = [(120, 6, 12, 4.25, [3.0, 9.4, 21.0])]
    fake.results["series"] = [
        (first, 20, 1, 2, 4.0, 8.0),
        (last, 100, 5, 10, 4.3, 9.9),
    ]
    fake.results["status_codes"] = [(2, 100), (4, 18), (5, 2)]
    fake.results["top_endpoints"] = [("/api/v1/hello", 120, 6, 12, 9.4)]


def test_usage_requires_a_token(client):
    assert client.get("/analytics/usage").status_code == 401


def test_usage_is_shaped_for_the_dashboard(client, user, fake_clickhouse, monkeypatch):
    monkeypatch.setattr(queries, "time", FrozenClock(NOW + 30))
    window = queries.window_for("24h", now=NOW + 30)
    _usage_rows(fake_clickhouse, window)

    body = client.get("/analytics/usage", headers=user["headers"]).json()

    assert body["range"] == "24h"
    assert body["step_seconds"] == 3600
    assert body["summary"] == {
        "requests": 120,
        "errors": 6,
        "rate_limited": 12,
        "error_rate": 5.0,
        "rate_limited_rate": 10.0,
        "avg_ms": 4.2,
        "p50_ms": 3.0,
        "p95_ms": 9.4,
        "p99_ms": 21.0,
    }
    assert body["status_codes"] == {"2xx": 100, "3xx": 0, "4xx": 18, "5xx": 2}
    assert body["top_endpoints"] == [
        {"endpoint": "/api/v1/hello", "requests": 120, "errors": 6, "rate_limited": 12, "p95_ms": 9.4}
    ]


def test_usage_series_is_zero_filled(client, user, fake_clickhouse, monkeypatch):
    monkeypatch.setattr(queries, "time", FrozenClock(NOW + 30))
    window = queries.window_for("24h", now=NOW + 30)
    _usage_rows(fake_clickhouse, window)

    series = client.get("/analytics/usage", headers=user["headers"]).json()["series"]

    assert [point["t"] for point in series] == window.bucket_starts
    assert series[0] == {"t": window.start, "requests": 20, "errors": 1, "rate_limited": 2, "avg_ms": 4.0, "p95_ms": 8.0}
    assert series[-1]["requests"] == 100
    # A bucket with no traffic is present, with no latency to report.
    assert series[5] == {"t": window.bucket_starts[5], "requests": 0, "errors": 0, "rate_limited": 0, "avg_ms": None, "p95_ms": None}


def test_usage_with_no_traffic_reports_zeros_and_null_latency(client, user, fake_clickhouse):
    nan = float("nan")
    fake_clickhouse.results["summary"] = [(0, 0, 0, nan, [nan, nan, nan])]

    summary = client.get("/analytics/usage?range=1h", headers=user["headers"]).json()["summary"]

    assert summary["requests"] == 0
    assert summary["error_rate"] == 0.0
    assert summary["p95_ms"] is None and summary["avg_ms"] is None


def test_usage_survives_an_empty_summary_result(client, user):
    """No rows at all (rather than one row of zeros) must not crash."""
    summary = client.get("/analytics/usage", headers=user["headers"]).json()["summary"]
    assert summary["requests"] == 0
    assert summary["p99_ms"] is None


def test_usage_ignores_status_classes_outside_2xx_to_5xx(client, user, fake_clickhouse):
    fake_clickhouse.results["status_codes"] = [(1, 3), (2, 10)]
    codes = client.get("/analytics/usage", headers=user["headers"]).json()["status_codes"]
    assert codes == {"2xx": 10, "3xx": 0, "4xx": 0, "5xx": 0}


def test_regular_users_only_see_their_own_traffic(client, user, fake_clickhouse):
    body = client.get("/analytics/usage", headers=user["headers"]).json()

    assert body["scope"] == {"user_id": user["id"], "username": user["username"]}
    for name in ("summary", "series", "status_codes", "top_endpoints"):
        call = fake_clickhouse.call(name)
        assert call["params"]["user_id"] == user["id"]
        assert "user_id = %(user_id)s" in call["sql"]


def test_regular_users_may_name_themselves(client, user):
    response = client.get(f"/analytics/usage?user_id={user['id']}", headers=user["headers"])
    assert response.status_code == 200


def test_regular_users_cannot_see_someone_else(client, user, user_factory):
    other = user_factory(username="someone-else")
    response = client.get(f"/analytics/usage?user_id={other['id']}", headers=user["headers"])
    assert response.status_code == 403


def test_admins_see_all_traffic_by_default(client, admin, fake_clickhouse):
    body = client.get("/analytics/usage", headers=admin["headers"]).json()

    assert body["scope"] == {"user_id": None, "username": None}
    call = fake_clickhouse.call("summary")
    assert "user_id" not in call["params"]
    assert "user_id =" not in call["sql"]


def test_admins_can_focus_on_one_user(client, admin, user, fake_clickhouse):
    body = client.get(f"/analytics/usage?user_id={user['id']}", headers=admin["headers"]).json()

    assert body["scope"] == {"user_id": user["id"], "username": user["username"]}
    assert fake_clickhouse.call("series")["params"]["user_id"] == user["id"]


def test_the_window_is_passed_as_parameters_not_sql(client, user, fake_clickhouse, monkeypatch):
    monkeypatch.setattr(queries, "time", FrozenClock(NOW + 30))
    client.get("/analytics/usage?range=7d", headers=user["headers"])

    params = fake_clickhouse.call("series")["params"]
    window = queries.window_for("7d", now=NOW + 30)
    assert (params["start"], params["end"], params["step"]) == (window.start, window.end, 21600)


@pytest.mark.parametrize("bad", ["2h", "", "24H", "1d"])
def test_unknown_ranges_are_rejected(client, user, bad):
    assert client.get(f"/analytics/usage?range={bad}", headers=user["headers"]).status_code == 422


def test_clickhouse_outage_is_a_503_not_a_500(client, user, fake_clickhouse):
    fake_clickhouse.down = True
    response = client.get("/analytics/usage", headers=user["headers"])
    assert response.status_code == 503
    assert response.json() == {"detail": "Analytics store unavailable"}


def test_analytics_is_not_behind_the_gateway(client, user, fake_clickhouse):
    """The dashboard authenticates with its own JWT, which the gateway would
    refuse; its routes must not demand a gateway token."""
    response = client.get("/analytics/usage", headers=user["headers"])
    assert response.status_code == 200


# --------------------------------------------------------------------------
# /analytics/rate-limits
# --------------------------------------------------------------------------

def test_rate_limit_series_splits_allowed_from_throttled(client, user, fake_clickhouse, monkeypatch):
    monkeypatch.setattr(queries, "time", FrozenClock(NOW + 30))
    window = queries.window_for("24h", now=NOW + 30)
    fake_clickhouse.results["series"] = [
        (window.bucket_starts[0], 10, 0, 4, 3.0, 5.0),
        (window.bucket_starts[-1], 30, 0, 6, 3.0, 5.0),
    ]
    fake_clickhouse.results["throttled_by_endpoint"] = [("/api/v1/hello", 40, 10)]

    body = client.get("/analytics/rate-limits", headers=user["headers"]).json()

    assert body["totals"] == {"requests": 40, "rate_limited": 10, "rate_limited_rate": 25.0}
    assert body["series"][0] == {"t": window.bucket_starts[0], "allowed": 6, "rate_limited": 4}
    assert body["series"][-1] == {"t": window.bucket_starts[-1], "allowed": 24, "rate_limited": 6}
    assert body["by_endpoint"] == [{"endpoint": "/api/v1/hello", "requests": 40, "rate_limited": 10}]


def test_only_admins_viewing_everyone_get_the_user_ranking(client, user, admin, fake_clickhouse):
    fake_clickhouse.results["throttled_by_user_id"] = [(user["id"], 50, 20), ("ghost", 5, 1)]

    own = client.get("/analytics/rate-limits", headers=user["headers"]).json()
    assert own["by_user"] == []
    assert "throttled_by_user_id" not in fake_clickhouse.names()

    everyone = client.get("/analytics/rate-limits", headers=admin["headers"]).json()
    assert everyone["by_user"] == [
        {"user_id": user["id"], "username": user["username"], "requests": 50, "rate_limited": 20},
        # Traffic from an account since deleted keeps its id, without a name.
        {"user_id": "ghost", "username": None, "requests": 5, "rate_limited": 1},
    ]


def test_admin_focused_on_one_user_gets_no_user_ranking(client, admin, user, fake_clickhouse):
    body = client.get(f"/analytics/rate-limits?user_id={user['id']}", headers=admin["headers"]).json()
    assert body["by_user"] == []
    assert "throttled_by_user_id" not in fake_clickhouse.names()


# --------------------------------------------------------------------------
# /analytics/logs
# --------------------------------------------------------------------------

def test_logs_are_newest_first_with_iso_timestamps(client, user, fake_clickhouse):
    fake_clickhouse.results["logs"] = [
        (NOW + 5, user["id"], "/api/v1/hello", 429, 0),
        (NOW, user["id"], "/api/v1/hello", 200, 3),
    ]

    body = client.get("/analytics/logs", headers=user["headers"]).json()

    assert body["range"] == "1h"
    assert body["truncated"] is False
    assert body["rows"][0] == {
        "timestamp": "2024-09-24T15:00:05Z",
        "user_id": user["id"],
        "username": user["username"],
        "endpoint": "/api/v1/hello",
        "status_code": 429,
        "response_time_ms": 0,
    }
    assert "ORDER BY timestamp DESC" in fake_clickhouse.call("logs")["sql"]


def test_logs_filters_are_applied_in_the_query(client, user, fake_clickhouse):
    client.get("/analytics/logs?status=5xx&endpoint=Hello", headers=user["headers"])

    call = fake_clickhouse.call("logs")
    assert call["params"]["status_class"] == 5
    assert call["params"]["endpoint"] == "Hello"
    assert "intDiv(status_code, 100) = %(status_class)s" in call["sql"]
    assert "positionCaseInsensitive(endpoint, %(endpoint)s)" in call["sql"]


def test_logs_without_filters_add_no_conditions(client, user, fake_clickhouse):
    client.get("/analytics/logs?status=all&endpoint=", headers=user["headers"])

    call = fake_clickhouse.call("logs")
    assert "status_class" not in call["params"]
    assert "endpoint" not in call["params"]


def test_logs_report_truncation(client, user, fake_clickhouse):
    rows = [(NOW - i, user["id"], "/api/v1/hello", 200, 1) for i in range(4)]
    fake_clickhouse.results["logs"] = rows

    body = client.get("/analytics/logs?limit=3", headers=user["headers"]).json()

    # One more row than the limit is fetched, to learn whether there are more.
    assert fake_clickhouse.call("logs")["params"]["limit"] == 4
    assert body["truncated"] is True
    assert len(body["rows"]) == 3


@pytest.mark.parametrize("query", ["status=6xx", "limit=0", "limit=1001", "range=90d"])
def test_logs_reject_bad_parameters(client, user, query):
    assert client.get(f"/analytics/logs?{query}", headers=user["headers"]).status_code == 422


def test_logs_are_scoped_like_everything_else(client, user, user_factory):
    other = user_factory(username="neighbour")
    response = client.get(f"/analytics/logs?user_id={other['id']}", headers=user["headers"])
    assert response.status_code == 403


# --------------------------------------------------------------------------
# /analytics/users
# --------------------------------------------------------------------------

def test_user_breakdown_is_for_admins_only(client, user):
    assert client.get("/analytics/users", headers=user["headers"]).status_code == 403


def test_user_breakdown_is_a_page_of_the_busiest_users(client, admin, user_factory, fake_clickhouse):
    busy = user_factory(username="busy")
    quiet = user_factory(username="quiet")
    fake_clickhouse.results["top_users"] = [
        (busy["id"], 90, 3, 9, 12.5, NOW),
        (quiet["id"], 4, 0, 0, 2.0, NOW - 60),
    ]
    fake_clickhouse.results["active_users"] = [(7,)]

    body = client.get("/analytics/users?range=7d&limit=2&offset=4", headers=admin["headers"]).json()

    assert (body["range"], body["total"], body["limit"], body["offset"]) == ("7d", 7, 2, 4)
    assert body["users"][0] == {
        "id": busy["id"],
        "username": "busy",
        "email": busy["email"],
        "is_active": True,
        "is_admin": False,
        "requests": 90,
        "errors": 3,
        "rate_limited": 9,
        "p95_ms": 12.5,
        "last_seen": NOW,
    }
    assert [u["username"] for u in body["users"]] == ["busy", "quiet"]
    # Ranking and paging happen in ClickHouse, across every user.
    page = fake_clickhouse.call("top_users")
    assert (page["params"]["limit"], page["params"]["offset"]) == (2, 4)
    assert "ORDER BY requests DESC, user_id" in page["sql"]
    assert "user_id =" not in page["sql"]


def test_user_breakdown_reads_only_the_page_from_the_database(client, admin, user_factory, fake_clickhouse):
    """The page's accounts are looked up by id, not by loading every user."""
    from sqlalchemy import event

    from backend.models import database

    ids = [user_factory(username=f"user{n}")["id"] for n in range(5)]
    fake_clickhouse.results["top_users"] = [(uid, 1, 0, 0, 1.0, NOW) for uid in ids[:2]]
    user_queries = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement:
            user_queries.append(parameters)

    event.listen(database.engine, "before_cursor_execute", record)
    try:
        client.get("/analytics/users", headers=admin["headers"])
    finally:
        event.remove(database.engine, "before_cursor_execute", record)

    # One lookup for the admin's token, one for the page's two accounts.
    assert sorted(ids[:2]) == sorted(user_queries[-1])


def test_user_breakdown_defaults_to_the_first_fifty(client, admin, fake_clickhouse):
    body = client.get("/analytics/users", headers=admin["headers"]).json()

    assert (body["total"], body["limit"], body["offset"], body["users"]) == (0, 50, 0, [])
    assert fake_clickhouse.call("top_users")["params"]["limit"] == 50


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
def test_user_breakdown_rejects_bad_pages(client, admin, query):
    assert client.get(f"/analytics/users?{query}", headers=admin["headers"]).status_code == 422


def test_traffic_from_a_deleted_account_is_still_listed(client, admin, fake_clickhouse):
    fake_clickhouse.results["top_users"] = [("gone", 5, 0, 0, 1.0, NOW)]
    fake_clickhouse.results["active_users"] = [(1,)]

    users = client.get("/analytics/users", headers=admin["headers"]).json()["users"]

    assert users == [
        {
            "id": "gone",
            "username": None,
            "email": None,
            "is_active": False,
            "is_admin": False,
            "requests": 5,
            "errors": 0,
            "rate_limited": 0,
            "p95_ms": 1.0,
            "last_seen": NOW,
        }
    ]


def test_nan_latency_never_reaches_json(client, admin, fake_clickhouse):
    fake_clickhouse.results["top_users"] = [(admin["id"], 4, 0, 4, float("nan"), NOW)]
    users = client.get("/analytics/users", headers=admin["headers"]).json()["users"]
    assert users[0]["p95_ms"] is None
    assert not any(isinstance(v, float) and math.isnan(v) for v in users[0].values())
