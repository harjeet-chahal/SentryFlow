"""Authentication, token handling and API-key lifecycle."""
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
