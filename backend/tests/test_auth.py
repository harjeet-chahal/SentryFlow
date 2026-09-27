"""Authentication, token handling and API-key lifecycle."""
import threading

import httpx
import jwt
import pytest

from backend.auth import auth_router
from backend.config import JWT_SECRET, settings


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

def test_signup_creates_a_user(client):
    response = client.post(
        "/auth/signup",
        json={"username": "alice", "email": "alice@example.com", "password": "s3cret-pass"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert "hashed_password" not in body, "password material must never be serialised"


def test_signup_rejects_a_duplicate_username(client, user):
    response = client.post(
        "/auth/signup",
        json={"username": user["username"], "email": "other@example.com", "password": "x" * 12},
    )
    assert response.status_code == 400


def test_signup_rejects_a_duplicate_email(client, user):
    response = client.post(
        "/auth/signup",
        json={"username": "someone-else", "email": user["email"], "password": "x" * 12},
    )
    assert response.status_code == 400


def test_signup_rejects_a_malformed_email(client):
    response = client.post(
        "/auth/signup",
        json={"username": "bob", "email": "not-an-email", "password": "x" * 12},
    )
    assert response.status_code == 422


def test_passwords_are_stored_hashed(client, user):
    from backend.models.database import SessionLocal
    from backend.models.models import User

    db = SessionLocal()
    try:
        record = db.query(User).filter(User.username == user["username"]).first()
    finally:
        db.close()

    assert record.hashed_password != user["password"]
    assert record.hashed_password.startswith("$2b$"), "expected a bcrypt hash"


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------

def test_login_returns_a_token_pair(client, user):
    response = client.post(
        "/auth/login", data={"username": user["username"], "password": user["password"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]


def test_login_rejects_a_wrong_password(client, user):
    response = client.post(
        "/auth/login", data={"username": user["username"], "password": "wrong"}
    )
    assert response.status_code == 401


def test_login_rejects_an_unknown_user(client):
    response = client.post("/auth/login", data={"username": "ghost", "password": "whatever"})
    assert response.status_code == 401


def test_login_requires_form_encoding_not_json(client, user):
    """Guards the OAuth2 password-flow contract the dashboard must speak."""
    response = client.post(
        "/auth/login", json={"username": user["username"], "password": user["password"]}
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

def test_access_and_refresh_tokens_are_distinguishable(user):
    access = jwt.decode(user["access_token"], JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    refresh = jwt.decode(user["refresh_token"], JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert access["type"] == "access"
    assert refresh["type"] == "refresh"


def test_refresh_token_is_rejected_as_an_access_token(client, user):
    """Without the type claim a refresh token would grant full API access."""
    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {user['refresh_token']}"}
    )
    assert response.status_code == 401


def test_access_token_is_rejected_at_the_refresh_endpoint(client, user):
    response = client.post("/auth/refresh", json={"refresh_token": user["access_token"]})
    assert response.status_code == 401


def test_refresh_issues_a_new_pair(client, user):
    response = client.post("/auth/refresh", json={"refresh_token": user["refresh_token"]})
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_refresh_rejects_a_garbage_token(client):
    response = client.post("/auth/refresh", json={"refresh_token": "not.a.jwt"})
    assert response.status_code == 401


def test_expired_token_is_rejected(client, user):
    from datetime import timedelta

    expired = auth_router.create_token(
        user["username"], auth_router.ACCESS_TOKEN_TYPE, timedelta(seconds=-10)
    )
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_token_signed_with_another_key_is_rejected(client, user):
    forged = jwt.encode(
        {"sub": user["username"], "type": "access"}, "attacker-key", algorithm="HS256"
    )
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_token_without_a_subject_is_rejected(client):
    token = jwt.encode({"type": "access"}, JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_token_for_a_deleted_user_is_rejected(client, user):
    from backend.models.database import SessionLocal
    from backend.models.models import User

    db = SessionLocal()
    try:
        db.query(User).filter(User.username == user["username"]).delete()
        db.commit()
    finally:
        db.close()

    response = client.get("/auth/me", headers=user["headers"])
    assert response.status_code == 401


def test_me_returns_the_authenticated_user(client, user):
    response = client.get("/auth/me", headers=user["headers"])
    assert response.status_code == 200
    assert response.json()["username"] == user["username"]
    assert response.json()["is_admin"] is False


def test_me_reports_the_admin_role(client, admin):
    assert client.get("/auth/me", headers=admin["headers"]).json()["is_admin"] is True


def test_signup_cannot_grant_the_admin_role(client):
    response = client.post(
        "/auth/signup",
        json={"username": "sneaky", "email": "s@example.com", "password": "pw-123456", "is_admin": True},
    )
    assert response.status_code == 201
    assert response.json()["is_admin"] is False


def test_me_requires_a_token(client):
    assert client.get("/auth/me").status_code == 401


# --------------------------------------------------------------------------
# API keys
# --------------------------------------------------------------------------

def test_create_api_key_returns_a_usable_secret(client, user):
    response = client.post(
        "/auth/apikeys/create", json={"name": "ci-pipeline"}, headers=user["headers"]
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "ci-pipeline"
    assert len(body["key"]) == 64, "expected 32 bytes of hex entropy"
    assert body["is_active"] is True


def test_api_keys_are_unique_per_creation(client, user):
    first = client.post("/auth/apikeys/create", json={"name": "a"}, headers=user["headers"])
    second = client.post("/auth/apikeys/create", json={"name": "b"}, headers=user["headers"])
    assert first.json()["key"] != second.json()["key"]


def test_create_api_key_requires_authentication(client):
    assert client.post("/auth/apikeys/create", json={"name": "x"}).status_code == 401


def test_listing_only_returns_your_own_keys(client, user_factory):
    alice = user_factory(username="alice")
    bob = user_factory(username="bob")

    client.post("/auth/apikeys/create", json={"name": "alice-key"}, headers=alice["headers"])
    client.post("/auth/apikeys/create", json={"name": "bob-key"}, headers=bob["headers"])

    listed = client.get("/auth/apikeys", headers=alice["headers"]).json()
    assert [k["name"] for k in listed] == ["alice-key"]


def test_revoking_a_key_deactivates_it(client, user, api_key):
    response = client.delete(f"/auth/apikeys/{api_key['id']}", headers=user["headers"])
    assert response.status_code == 204

    listed = client.get("/auth/apikeys", headers=user["headers"]).json()
    assert listed[0]["is_active"] is False


def test_cannot_revoke_someone_elses_key(client, user_factory, api_key):
    intruder = user_factory(username="intruder")
    response = client.delete(f"/auth/apikeys/{api_key['id']}", headers=intruder["headers"])
    assert response.status_code == 404


def test_revoking_a_missing_key_is_a_404(client, user):
    response = client.delete("/auth/apikeys/does-not-exist", headers=user["headers"])
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Gateway tokens, traded for API keys
# --------------------------------------------------------------------------

def test_an_api_key_buys_a_short_lived_gateway_token(client, user, api_key):
    response = client.post("/auth/token", headers={"x-api-key": api_key["key"]})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.GATEWAY_TOKEN_EXPIRE_MINUTES * 60

    claims = jwt.decode(body["access_token"], JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert claims["type"] == "gateway"
    assert claims["sub"] == user["id"]
    assert claims["key_id"] == api_key["id"]


def test_the_exchange_requires_a_key(client):
    response = client.post("/auth/token")
    assert response.status_code == 401
    assert "x-api-key" in response.json()["detail"]


def test_the_exchange_rejects_an_unknown_key(client):
    response = client.post("/auth/token", headers={"x-api-key": "0" * 64})
    assert response.status_code == 401


def test_a_revoked_key_cannot_be_exchanged(client, user, api_key):
    client.delete(f"/auth/apikeys/{api_key['id']}", headers=user["headers"])
    response = client.post("/auth/token", headers={"x-api-key": api_key["key"]})
    assert response.status_code == 401


def test_a_dashboard_token_cannot_be_exchanged(client, user):
    """Only an API key buys a gateway token; a signed-in session does not."""
    assert client.post("/auth/token", headers=user["headers"]).status_code == 401


def test_a_gateway_token_is_not_a_dashboard_token(client, gateway_headers):
    """It calls the API; it cannot manage the account that owns it."""
    assert client.get("/auth/me", headers=gateway_headers).status_code == 401
    assert client.get("/auth/apikeys", headers=gateway_headers).status_code == 401


# --------------------------------------------------------------------------
# Password hashing must not stall the gateway
# --------------------------------------------------------------------------

def _record_threads(monkeypatch, method):
    """Wrap a CryptContext method to record which thread runs it."""
    threads = []
    real = getattr(auth_router.pwd_context, method)

    def spy(*args, **kwargs):
        threads.append(threading.get_ident())
        return real(*args, **kwargs)

    monkeypatch.setattr(auth_router.pwd_context, method, spy)
    return threads


async def test_login_checks_the_password_off_the_event_loop(app, user, monkeypatch):
    """bcrypt costs ~200 ms of CPU. Run on the event loop, it stalls every
    request in flight for that long; the load test showed it as p99 spikes."""
    threads = _record_threads(monkeypatch, "verify")

    async with httpx.AsyncClient(app=app, base_url="http://gateway") as ac:
        response = await ac.post(
            "/auth/login", data={"username": user["username"], "password": user["password"]}
        )

    assert response.status_code == 200
    assert threads and threading.get_ident() not in threads


async def test_signup_hashes_the_password_off_the_event_loop(app, monkeypatch):
    threads = _record_threads(monkeypatch, "hash")

    async with httpx.AsyncClient(app=app, base_url="http://gateway") as ac:
        response = await ac.post(
            "/auth/signup",
            json={"username": "hasher", "email": "hasher@example.com", "password": "pw-123456"},
        )

    assert response.status_code == 201
    assert threads and threading.get_ident() not in threads


# --------------------------------------------------------------------------
# User directory
# --------------------------------------------------------------------------

def test_the_user_directory_is_for_admins_only(client, user):
    assert client.get("/auth/users").status_code == 401
    assert client.get("/auth/users", headers=user["headers"]).status_code == 403


def test_the_user_directory_pages_accounts_by_username(client, admin, user_factory):
    for name in ("carol", "alice", "bob"):
        user_factory(username=name)

    first = client.get("/auth/users?limit=2", headers=admin["headers"]).json()
    rest = client.get("/auth/users?limit=2&offset=2", headers=admin["headers"]).json()

    assert first["total"] == rest["total"] == 4
    assert [u["username"] for u in first["users"]] == ["alice", "bob"]
    assert [u["username"] for u in rest["users"]] == ["carol", "operator"]
    assert set(first["users"][0]) >= {"id", "username", "email", "is_active", "is_admin"}
    assert "hashed_password" not in first["users"][0]


def test_the_user_directory_searches_usernames_and_emails(client, admin, user_factory):
    user_factory(username="alice", email="alice@acme.example.com")
    user_factory(username="bob", email="bob@ACME.example.com")
    user_factory(username="carol", email="carol@example.org")

    def names(search):
        body = client.get("/auth/users", params={"search": search}, headers=admin["headers"]).json()
        return [u["username"] for u in body["users"]], body["total"]

    assert names("acme") == (["alice", "bob"], 2)  # email, case-insensitively
    assert names("CAR") == (["carol"], 1)  # username, case-insensitively
    assert names("nobody") == ([], 0)


def test_the_user_directory_takes_wildcards_literally(client, admin, user_factory):
    user_factory(username="under_score")
    user_factory(username="underxscore")

    body = client.get("/auth/users", params={"search": "under_"}, headers=admin["headers"]).json()
    assert [u["username"] for u in body["users"]] == ["under_score"]

    body = client.get("/auth/users", params={"search": "%"}, headers=admin["headers"]).json()
    assert body["users"] == []


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", f"search={'x' * 101}"])
def test_the_user_directory_rejects_bad_parameters(client, admin, query):
    assert client.get(f"/auth/users?{query}", headers=admin["headers"]).status_code == 422
