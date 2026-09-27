"""End-to-end tests for the gateway middleware chain.

These drive real HTTP requests through authentication, rate limiting and
usage logging in the order the middleware applies them.
"""
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from backend.config import JWT_SECRET, settings
from backend.main import is_gateway_exempt
from backend.middlewares import logging_middleware
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


def _claims(user, api_key, **overrides):
    """What /auth/token would sign for this key, with some claims replaced."""
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user["id"],
        "type": "gateway",
        "key_id": api_key["id"],
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return claims


def _sign(claims, secret=JWT_SECRET):
    return jwt.encode(claims, secret, algorithm=settings.JWT_ALGORITHM)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# Public paths
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "/health", "/health/ready", "/health/live", "/docs", "/openapi.json", "/auth/login", "/",
        # Where programs get their gateway tokens.
        "/auth/token",
        # Dashboard APIs: authenticated per route with a dashboard JWT.
        "/analytics/usage", "/limits", "/limits/some-rule-id",
    ],
)
def test_exempt_paths_bypass_the_gateway(path):
    assert is_gateway_exempt(path) is True


@pytest.mark.parametrize(
    "path", ["/api/v1/hello", "/api/v1/anything", "/healthz", "/authz", "/analyticsx", "/limitsx"]
)
def test_other_paths_require_a_token(path):
    assert is_gateway_exempt(path) is False


def test_probes_are_reachable_without_credentials(client):
    """Kubelet cannot present a token, so probes must be unauthenticated."""
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

def test_request_without_a_token_is_rejected(client):
    response = client.get("/api/v1/hello")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "/auth/token" in response.json()["detail"]


def test_an_api_key_alone_does_not_get_through(client, api_key):
    """The key is only good at /auth/token; the gateway wants the token."""
    response = client.get("/api/v1/hello", headers={"x-api-key": api_key["key"]})
    assert response.status_code == 401


@pytest.mark.parametrize("header", ["Basic dXNlcjpwYXNz", "Bearer", "Bearer   ", "no-scheme"])
def test_other_authorization_headers_are_rejected(client, header):
    response = client.get("/api/v1/hello", headers={"Authorization": header})
    assert response.status_code == 401


def test_a_valid_token_gets_through(client, gateway_headers):
    response = client.get("/api/v1/hello", headers=gateway_headers)
    assert response.status_code == 200
    assert response.json() == {"message": "Hello from SentryFlow!"}


def test_the_bearer_scheme_is_case_insensitive(client, gateway_headers):
    token = gateway_headers["Authorization"].split(" ", 1)[1]
    response = client.get("/api/v1/hello", headers={"Authorization": f"bearer {token}"})
    assert response.status_code == 200


def test_a_garbage_token_is_rejected(client):
    response = client.get("/api/v1/hello", headers=_bearer("not-a-jwt"))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"'


def test_an_expired_token_is_rejected(client, user, api_key):
    expired = _claims(user, api_key, exp=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert client.get("/api/v1/hello", headers=_bearer(_sign(expired))).status_code == 401


def test_a_token_signed_with_another_key_is_rejected(client, user, api_key):
    forged = _sign(_claims(user, api_key), secret="not-the-server-secret")
    assert client.get("/api/v1/hello", headers=_bearer(forged)).status_code == 401


def test_an_unsigned_token_is_rejected(client, user, api_key):
    """alg=none is the classic JWT bypass; only the configured algorithm counts."""
    unsigned = jwt.encode(_claims(user, api_key), None, algorithm="none")
    assert client.get("/api/v1/hello", headers=_bearer(unsigned)).status_code == 401


@pytest.mark.parametrize("claim", ["sub", "key_id", "exp"])
def test_a_token_missing_a_required_claim_is_rejected(client, user, api_key, claim):
    claims = _claims(user, api_key)
    del claims[claim]
    assert client.get("/api/v1/hello", headers=_bearer(_sign(claims))).status_code == 401


def test_dashboard_tokens_are_not_gateway_tokens(client, user):
    """Same signing key, different job: a dashboard session manages the
    account and must not double as an API credential."""
    assert client.get("/api/v1/hello", headers=user["headers"]).status_code == 401
    refresh = _bearer(user["refresh_token"])
    assert client.get("/api/v1/hello", headers=refresh).status_code == 401


def test_revoking_a_key_stops_its_tokens_on_the_next_request(client, user, api_key, gateway_headers):
    """A token that has not expired must not outlive its key's revocation."""
    assert client.get("/api/v1/hello", headers=gateway_headers).status_code == 200

    client.delete(f"/auth/apikeys/{api_key['id']}", headers=user["headers"])

    assert client.get("/api/v1/hello", headers=gateway_headers).status_code == 401


def test_revoking_a_key_leaves_the_users_other_keys_working(
    client, user, api_key, gateway_headers, gateway_headers_for
):
    other = client.post("/auth/apikeys/create", json={"name": "other"}, headers=user["headers"])
    other_headers = gateway_headers_for(other.json()["key"])

    client.delete(f"/auth/apikeys/{api_key['id']}", headers=user["headers"])

    assert client.get("/api/v1/hello", headers=gateway_headers).status_code == 401
    assert client.get("/api/v1/hello", headers=other_headers).status_code == 200


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------

def test_successful_responses_carry_rate_limit_headers(client, gateway_headers):
    response = client.get("/api/v1/hello", headers=gateway_headers)
    assert response.headers["X-RateLimit-Limit"] == str(settings.DEFAULT_REQUESTS_PER_MINUTE)
    assert int(response.headers["X-RateLimit-Remaining"]) >= 0


def test_remaining_header_decrements_across_requests(client, gateway_headers):
    headers = gateway_headers
    first = client.get("/api/v1/hello", headers=headers)
    second = client.get("/api/v1/hello", headers=headers)

    assert int(second.headers["X-RateLimit-Remaining"]) < int(
        first.headers["X-RateLimit-Remaining"]
    )


def test_exceeding_the_limit_returns_429_with_retry_after(client, user, gateway_headers):
    _set_limit(user["id"], rpm=2)
    headers = gateway_headers

    assert client.get("/api/v1/hello", headers=headers).status_code == 200
    assert client.get("/api/v1/hello", headers=headers).status_code == 200

    blocked = client.get("/api/v1/hello", headers=headers)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


def test_rate_limits_are_scoped_per_user(client, user_factory, gateway_headers_for):
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
    as_alice = gateway_headers_for(alice_key)
    as_bob = gateway_headers_for(bob_key)

    assert client.get("/api/v1/hello", headers=as_alice).status_code == 200
    assert client.get("/api/v1/hello", headers=as_alice).status_code == 429

    # Bob's budget is untouched.
    assert client.get("/api/v1/hello", headers=as_bob).status_code == 200


def test_unauthenticated_requests_never_consume_a_budget(client, user, gateway_headers):
    """Auth precedes rate limiting, so bad tokens cannot burn a user's quota."""
    _set_limit(user["id"], rpm=2)

    for _ in range(10):
        client.get("/api/v1/hello", headers=_bearer("bogus"))

    headers = gateway_headers
    assert client.get("/api/v1/hello", headers=headers).status_code == 200
    assert client.get("/api/v1/hello", headers=headers).status_code == 200


# --------------------------------------------------------------------------
# Usage logging
# --------------------------------------------------------------------------

def test_served_requests_emit_a_usage_event(client, gateway_headers, published):
    client.get("/api/v1/hello", headers=gateway_headers)

    events = published().events_on(settings.API_REQUESTS_TOPIC)
    assert len(events) == 1
    event = events[0]
    assert event["endpoint"] == "/api/v1/hello"
    assert event["status_code"] == 200
    assert event["response_time"] >= 0
    assert event["timestamp"]


def test_throttled_requests_are_logged_to_their_own_topic(client, user, gateway_headers, published):
    _set_limit(user["id"], rpm=1)
    headers = gateway_headers

    client.get("/api/v1/hello", headers=headers)
    client.get("/api/v1/hello", headers=headers)

    throttled = published().events_on(settings.RATE_LIMITED_TOPIC)
    assert len(throttled) == 1
    assert throttled[0]["status_code"] == 429


class SteppingClock:
    """perf_counter that advances by a fixed step on every call."""

    def __init__(self, step):
        self.now, self.step = 100.0, step

    def perf_counter(self):
        self.now += self.step
        return self.now


def test_response_time_covers_the_whole_gateway_path(client, gateway_headers, published, monkeypatch):
    import backend.main as gateway

    # Two readings: on arrival and once the handler has answered.
    monkeypatch.setattr(gateway, "time", SteppingClock(step=0.0034))
    client.get("/api/v1/hello", headers=gateway_headers)

    assert published().events_on(settings.API_REQUESTS_TOPIC)[0]["response_time"] == 3


def test_sub_millisecond_requests_round_rather_than_truncate(client, gateway_headers, published, monkeypatch):
    import backend.main as gateway

    monkeypatch.setattr(gateway, "time", SteppingClock(step=0.0006))
    client.get("/api/v1/hello", headers=gateway_headers)

    assert published().events_on(settings.API_REQUESTS_TOPIC)[0]["response_time"] == 1


def test_throttled_requests_record_their_real_time(client, user, gateway_headers, published, monkeypatch):
    import backend.main as gateway

    _set_limit(user["id"], rpm=1)
    headers = gateway_headers
    client.get("/api/v1/hello", headers=headers)

    monkeypatch.setattr(gateway, "time", SteppingClock(step=0.002))
    client.get("/api/v1/hello", headers=headers)

    assert published().events_on(settings.RATE_LIMITED_TOPIC)[0]["response_time"] == 2


def test_events_are_partitioned_by_user(client, gateway_headers, published, user):
    client.get("/api/v1/hello", headers=gateway_headers)
    assert published().sent[0]["key"] == user["id"].encode("utf-8")


def test_a_kafka_outage_does_not_break_requests(client, gateway_headers, fake_kafka):
    """Analytics are best-effort; losing Kafka must not surface to callers."""
    fake_kafka.fail = True
    response = client.get("/api/v1/hello", headers=gateway_headers)
    assert response.status_code == 200


def test_a_stalled_broker_does_not_slow_requests(monkeypatch, client, gateway_headers, fake_kafka):
    """With the broker down, aiokafka's send() waits up to 40 s for buffer
    space. Only the background publisher may wait; callers must not."""
    monkeypatch.setattr(logging_middleware, "SHUTDOWN_TIMEOUT_SECONDS", 0.05)
    fake_kafka.stall = 2.0
    headers = gateway_headers

    started = time.perf_counter()
    statuses = [client.get("/api/v1/hello", headers=headers).status_code for _ in range(3)]
    elapsed = time.perf_counter() - started

    assert statuses == [200, 200, 200]
    assert elapsed < 1.0, f"requests waited on Kafka: {elapsed:.2f}s"
