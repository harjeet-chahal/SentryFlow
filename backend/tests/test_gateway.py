"""End-to-end tests for the gateway middleware chain.

These drive real HTTP requests through authentication, rate limiting and
usage logging in the order the middleware applies them.
"""
import pytest

from backend.config import settings
from backend.main import is_public_path
from backend.models.database import SessionLocal
from backend.models.models import RateLimit


def _set_limit(user_id, rpm, algorithm="sliding_window", burst=10):
    db = SessionLocal()
    try:
        db.add(
            RateLimit(
                user_id=user_id,
                endpoint="*",
                requests_per_minute=rpm,
                burst_capacity=burst,
                algorithm=algorithm,
            )
        )
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------
# Public paths
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    ["/health", "/health/ready", "/health/live", "/docs", "/openapi.json", "/auth/login", "/"],
)
def test_public_paths_bypass_api_key_enforcement(path):
    assert is_public_path(path) is True


@pytest.mark.parametrize("path", ["/api/v1/hello", "/api/v1/anything", "/healthz", "/authz"])
def test_protected_paths_require_a_key(path):
    assert is_public_path(path) is False


def test_probes_are_reachable_without_credentials(client):
    """Kubelet cannot present an API key, so probes must be unauthenticated."""
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

def test_request_without_an_api_key_is_rejected(client):
    response = client.get("/api/v1/hello")
    assert response.status_code == 401
    assert "x-api-key" in response.json()["detail"].lower()


def test_request_with_an_unknown_api_key_is_rejected(client):
    response = client.get("/api/v1/hello", headers={"x-api-key": "0" * 64})
    assert response.status_code == 401


def test_request_with_a_valid_api_key_succeeds(client, api_key):
    response = client.get("/api/v1/hello", headers={"x-api-key": api_key["key"]})
    assert response.status_code == 200
    assert response.json() == {"message": "Hello from SentryFlow!"}


def test_revoked_key_stops_working_immediately(client, user, api_key):
    """Revocation must evict the cache, not wait for the TTL to lapse."""
    headers = {"x-api-key": api_key["key"]}
    assert client.get("/api/v1/hello", headers=headers).status_code == 200

    client.delete(f"/auth/apikeys/{api_key['id']}", headers=user["headers"])

    assert client.get("/api/v1/hello", headers=headers).status_code == 401


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------

def test_successful_responses_carry_rate_limit_headers(client, api_key):
    response = client.get("/api/v1/hello", headers={"x-api-key": api_key["key"]})
    assert response.headers["X-RateLimit-Limit"] == str(settings.DEFAULT_REQUESTS_PER_MINUTE)
    assert int(response.headers["X-RateLimit-Remaining"]) >= 0


def test_remaining_header_decrements_across_requests(client, api_key):
    headers = {"x-api-key": api_key["key"]}
    first = client.get("/api/v1/hello", headers=headers)
    second = client.get("/api/v1/hello", headers=headers)

    assert int(second.headers["X-RateLimit-Remaining"]) < int(
        first.headers["X-RateLimit-Remaining"]
    )


def test_exceeding_the_limit_returns_429_with_retry_after(client, user, api_key):
    _set_limit(user["id"], rpm=2)
    headers = {"x-api-key": api_key["key"]}

    assert client.get("/api/v1/hello", headers=headers).status_code == 200
    assert client.get("/api/v1/hello", headers=headers).status_code == 200

    blocked = client.get("/api/v1/hello", headers=headers)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


def test_rate_limits_are_scoped_per_user(client, user_factory):
    """One caller exhausting its budget must not affect another."""
    alice = user_factory(username="alice")
    bob = user_factory(username="bob")
    _set_limit(alice["id"], rpm=1)
    _set_limit(bob["id"], rpm=1)

    alice_key = client.post(
        "/auth/apikeys/create", json={"name": "k"}, headers=alice["headers"]
    ).json()["key"]
    bob_key = client.post(
        "/auth/apikeys/create", json={"name": "k"}, headers=bob["headers"]
    ).json()["key"]

    assert client.get("/api/v1/hello", headers={"x-api-key": alice_key}).status_code == 200
    assert client.get("/api/v1/hello", headers={"x-api-key": alice_key}).status_code == 429

    # Bob's budget is untouched.
    assert client.get("/api/v1/hello", headers={"x-api-key": bob_key}).status_code == 200


def test_unauthenticated_requests_never_consume_a_budget(client, user, api_key):
    """Auth precedes rate limiting, so bad keys cannot burn a user's quota."""
    _set_limit(user["id"], rpm=2)

    for _ in range(10):
        client.get("/api/v1/hello", headers={"x-api-key": "bogus"})

    headers = {"x-api-key": api_key["key"]}
    assert client.get("/api/v1/hello", headers=headers).status_code == 200
    assert client.get("/api/v1/hello", headers=headers).status_code == 200


# --------------------------------------------------------------------------
# Usage logging
# --------------------------------------------------------------------------

def test_served_requests_emit_a_usage_event(client, api_key, fake_kafka):
    client.get("/api/v1/hello", headers={"x-api-key": api_key["key"]})

    events = fake_kafka.events_on(settings.API_REQUESTS_TOPIC)
    assert len(events) == 1
    event = events[0]
    assert event["endpoint"] == "/api/v1/hello"
    assert event["status_code"] == 200
    assert event["response_time"] >= 0
    assert event["timestamp"]


def test_throttled_requests_are_logged_to_their_own_topic(client, user, api_key, fake_kafka):
    _set_limit(user["id"], rpm=1)
    headers = {"x-api-key": api_key["key"]}

    client.get("/api/v1/hello", headers=headers)
    client.get("/api/v1/hello", headers=headers)

    throttled = fake_kafka.events_on(settings.RATE_LIMITED_TOPIC)
    assert len(throttled) == 1
    assert throttled[0]["status_code"] == 429


def test_events_are_partitioned_by_user(client, api_key, fake_kafka, user):
    client.get("/api/v1/hello", headers={"x-api-key": api_key["key"]})
    assert fake_kafka.sent[0]["key"] == user["id"].encode("utf-8")


def test_a_kafka_outage_does_not_break_requests(client, api_key, fake_kafka):
    """Analytics are best-effort; losing Kafka must not surface to callers."""
    fake_kafka.fail = True
    response = client.get("/api/v1/hello", headers={"x-api-key": api_key["key"]})
    assert response.status_code == 200
