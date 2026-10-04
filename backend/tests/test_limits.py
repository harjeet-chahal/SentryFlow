"""Rate-limit rules API: who may read and change them, and that changes bite.

The last group drives real requests through the gateway, because the point
of editing a limit is that the next request obeys it -- not the next request
after the config cache expires.
"""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import SessionLocal
from backend.models.models import RateLimit


def _rule(user_id, endpoint="*", rpm=100, burst=20, algorithm="sliding_window"):
    return {
        "user_id": user_id,
        "endpoint": endpoint,
        "requests_per_minute": rpm,
        "burst_capacity": burst,
        "algorithm": algorithm,
    }


def _add_rule(user_id, endpoint="*", rpm=100):
    db = SessionLocal()
    try:
        db.add(RateLimit(user_id=user_id, endpoint=endpoint, requests_per_minute=rpm))
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def test_listing_requires_a_token(client):
    assert client.get("/limits").status_code == 401


def test_listing_includes_the_defaults(client, user):
    body = client.get("/limits", headers=user["headers"]).json()
    assert body["defaults"] == {
        "requests_per_minute": settings.DEFAULT_REQUESTS_PER_MINUTE,
        "burst_capacity": settings.DEFAULT_BURST_CAPACITY,
        "algorithm": settings.DEFAULT_ALGORITHM,
        "window_seconds": settings.DEFAULT_RATE_LIMIT_WINDOW,
    }
    assert body["rules"] == []


def test_users_see_only_their_own_rules(client, user, user_factory):
    other = user_factory(username="other")
    _add_rule(user["id"], "/api/v1/hello", rpm=5)
    _add_rule(other["id"], "*", rpm=500)

    rules = client.get("/limits", headers=user["headers"]).json()["rules"]

    assert len(rules) == 1
    assert rules[0]["user_id"] == user["id"]
    assert rules[0]["username"] == user["username"]
    assert rules[0]["endpoint"] == "/api/v1/hello"
    assert rules[0]["requests_per_minute"] == 5


def test_users_cannot_list_someone_elses_rules(client, user, user_factory):
    other = user_factory(username="other")
    response = client.get(f"/limits?user_id={other['id']}", headers=user["headers"])
    assert response.status_code == 403


def test_admins_see_every_rule_or_one_users(client, admin, user):
    _add_rule(user["id"], "*", rpm=5)
    _add_rule(admin["id"], "*", rpm=9)

    everyone = client.get("/limits", headers=admin["headers"]).json()["rules"]
    assert {r["username"] for r in everyone} == {user["username"], admin["username"]}

    one = client.get(f"/limits?user_id={user['id']}", headers=admin["headers"]).json()["rules"]
    assert [r["user_id"] for r in one] == [user["id"]]


def test_rule_timestamps_carry_a_utc_offset(client, user):
    """A bare timestamp would be read as local time by the browser."""
    _add_rule(user["id"])
    updated = client.get("/limits", headers=user["headers"]).json()["rules"][0]["updated_at"]
    assert updated.endswith("+00:00")


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def test_only_admins_can_change_limits(client, user):
    response = client.put("/limits", json=_rule(user["id"], rpm=100000), headers=user["headers"])
    assert response.status_code == 403
    assert client.get("/limits", headers=user["headers"]).json()["rules"] == []


def test_only_admins_can_delete_limits(client, user):
    _add_rule(user["id"])
    rule_id = client.get("/limits", headers=user["headers"]).json()["rules"][0]["id"]
    assert client.delete(f"/limits/{rule_id}", headers=user["headers"]).status_code == 403


def test_admin_creates_then_updates_one_rule(client, admin, user):
    created = client.put("/limits", json=_rule(user["id"], rpm=10), headers=admin["headers"])
    assert created.status_code == 200
    assert created.json()["requests_per_minute"] == 10

    updated = client.put(
        "/limits", json=_rule(user["id"], rpm=25, algorithm="token_bucket", burst=5), headers=admin["headers"]
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["id"] == created.json()["id"]
    assert (body["requests_per_minute"], body["algorithm"], body["burst_capacity"]) == (25, "token_bucket", 5)

    rules = client.get(f"/limits?user_id={user['id']}", headers=admin["headers"]).json()["rules"]
    assert len(rules) == 1


def test_rules_for_different_endpoints_are_separate(client, admin, user):
    client.put("/limits", json=_rule(user["id"], "*", rpm=10), headers=admin["headers"])
    client.put("/limits", json=_rule(user["id"], "/api/v1/hello", rpm=3), headers=admin["headers"])

    rules = client.get(f"/limits?user_id={user['id']}", headers=admin["headers"]).json()["rules"]
    assert sorted(r["endpoint"] for r in rules) == ["*", "/api/v1/hello"]


def test_limits_for_an_unknown_user_are_a_404(client, admin):
    response = client.put("/limits", json=_rule("no-such-user"), headers=admin["headers"])
    assert response.status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"algorithm": "fixed_window"},
        {"requests_per_minute": 0},
        {"requests_per_minute": 2_000_000},
        {"burst_capacity": 0},
        {"endpoint": "api/v1/hello"},
        {"endpoint": ""},
    ],
)
def test_invalid_rules_are_rejected(client, admin, user, change):
    response = client.put("/limits", json={**_rule(user["id"]), **change}, headers=admin["headers"])
    assert response.status_code == 422


def test_endpoint_whitespace_is_trimmed(client, admin, user):
    response = client.put("/limits", json=_rule(user["id"], " * "), headers=admin["headers"])
    assert response.json()["endpoint"] == "*"


def test_a_concurrent_create_is_reported_as_a_conflict(client, admin, user, monkeypatch):
    def lose_the_race(self):
        raise IntegrityError("INSERT INTO rate_limits", {}, Exception("duplicate key"))

    monkeypatch.setattr(Session, "commit", lose_the_race)
    response = client.put("/limits", json=_rule(user["id"]), headers=admin["headers"])
    assert response.status_code == 409


def test_admin_deletes_a_rule(client, admin, user):
    rule = client.put("/limits", json=_rule(user["id"]), headers=admin["headers"]).json()

    assert client.delete(f"/limits/{rule['id']}", headers=admin["headers"]).status_code == 204
    assert client.get(f"/limits?user_id={user['id']}", headers=admin["headers"]).json()["rules"] == []


def test_deleting_a_missing_rule_is_a_404(client, admin):
    assert client.delete("/limits/nope", headers=admin["headers"]).status_code == 404


# --------------------------------------------------------------------------
# Changes take effect on the very next request
# --------------------------------------------------------------------------

def _hello(client, headers):
    return client.get("/api/v1/hello", headers=headers)


def test_lowering_a_limit_applies_immediately(client, admin, user, gateway_headers):
    # The first request caches "no rule, use the defaults" for 60 seconds.
    assert _hello(client, gateway_headers).status_code == 200

    client.put("/limits", json=_rule(user["id"], rpm=2), headers=admin["headers"])

    assert _hello(client, gateway_headers).status_code == 200
    blocked = _hello(client, gateway_headers)
    assert blocked.status_code == 429
    assert blocked.headers["X-RateLimit-Limit"] == "2"


def test_deleting_a_limit_restores_the_defaults_immediately(client, admin, user, gateway_headers):
    rule = client.put("/limits", json=_rule(user["id"], rpm=1), headers=admin["headers"]).json()
    assert _hello(client, gateway_headers).status_code == 200
    assert _hello(client, gateway_headers).status_code == 429

    client.delete(f"/limits/{rule['id']}", headers=admin["headers"])

    response = _hello(client, gateway_headers)
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == str(settings.DEFAULT_REQUESTS_PER_MINUTE)


def test_a_rule_for_one_endpoint_leaves_the_others_alone(client, admin, user, gateway_headers):
    client.put("/limits", json=_rule(user["id"], "/api/v1/other", rpm=1), headers=admin["headers"])
    response = _hello(client, gateway_headers)
    assert response.headers["X-RateLimit-Limit"] == str(settings.DEFAULT_REQUESTS_PER_MINUTE)
