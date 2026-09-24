"""Database bootstrap: schema creation, upgrades and idempotent seeding."""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from backend import setup_db
from backend.config import settings
from backend.models.database import SessionLocal, engine
from backend.models.models import RateLimit, User


def test_init_db_is_safe_to_rerun():
    setup_db.init_db()
    setup_db.init_db()


def test_creates_the_admin_user():
    admin = setup_db.create_admin_user()
    assert admin.username == setup_db.ADMIN_USERNAME
    assert admin.is_active is True


def test_admin_password_is_hashed_not_stored(monkeypatch):
    monkeypatch.setenv("SENTRYFLOW_ADMIN_PASSWORD", "chosen-password")
    admin = setup_db.create_admin_user()
    assert admin.hashed_password != "chosen-password"
    assert setup_db.pwd_context.verify("chosen-password", admin.hashed_password)


def test_creating_the_admin_twice_does_not_duplicate():
    first = setup_db.create_admin_user()
    second = setup_db.create_admin_user()
    assert first.id == second.id

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.username == setup_db.ADMIN_USERNAME).count() == 1
    finally:
        db.close()


def test_supplied_password_is_used_verbatim(monkeypatch):
    monkeypatch.setenv("SENTRYFLOW_ADMIN_PASSWORD", "from-the-environment")
    password, generated = setup_db._resolve_admin_password()
    assert password == "from-the-environment"
    assert generated is False


def test_password_is_generated_when_unset(monkeypatch):
    """A fresh deploy must not fall back to a default credential in source."""
    monkeypatch.delenv("SENTRYFLOW_ADMIN_PASSWORD", raising=False)
    first, generated = setup_db._resolve_admin_password()
    second, _ = setup_db._resolve_admin_password()

    assert generated is True
    assert len(first) >= 24
    assert first != second


def test_seeds_a_default_rate_limit():
    setup_db.create_admin_user()
    rule = setup_db.setup_default_rate_limits()

    assert rule.endpoint == "*"
    assert rule.requests_per_minute == settings.DEFAULT_REQUESTS_PER_MINUTE
    assert rule.algorithm == settings.DEFAULT_ALGORITHM


def test_seeding_the_rate_limit_twice_does_not_duplicate():
    setup_db.create_admin_user()
    first = setup_db.setup_default_rate_limits()
    second = setup_db.setup_default_rate_limits()
    assert first.id == second.id

    db = SessionLocal()
    try:
        assert db.query(RateLimit).filter(RateLimit.endpoint == "*").count() == 1
    finally:
        db.close()


def test_rate_limit_seeding_is_skipped_without_an_admin():
    assert setup_db.setup_default_rate_limits() is None


def test_main_runs_the_full_bootstrap():
    assert setup_db.main([]) == 0

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.username == setup_db.ADMIN_USERNAME).count() == 1
        assert db.query(RateLimit).filter(RateLimit.endpoint == "*").count() == 1
    finally:
        db.close()


# --------------------------------------------------------------------------
# Administrators
# --------------------------------------------------------------------------

def test_the_seeded_admin_is_an_administrator():
    assert setup_db.create_admin_user().is_admin is True


def test_an_existing_account_with_the_admin_name_is_not_promoted(client, user_factory, caplog):
    """Someone could have signed up as "admin" before this ever ran."""
    squatter = user_factory(username=setup_db.ADMIN_USERNAME)

    with caplog.at_level("WARNING"):
        existing = setup_db.create_admin_user()

    assert existing.id == squatter["id"]
    assert existing.is_admin is False
    assert "--grant-admin" in caplog.text


def test_grant_admin_promotes_an_existing_user(client, user):
    assert setup_db.grant_admin(user["username"]) is True

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.id == user["id"]).one().is_admin is True
    finally:
        db.close()


def test_grant_admin_reports_a_missing_user():
    assert setup_db.grant_admin("nobody") is False


def test_main_can_grant_the_admin_role(client, user):
    assert setup_db.main(["--grant-admin", user["username"]]) == 0
    assert setup_db.main(["--grant-admin", "nobody"]) == 1


# --------------------------------------------------------------------------
# Upgrading a database created by an older release
# --------------------------------------------------------------------------

LEGACY_USERS = """
CREATE TABLE users (
    id VARCHAR(36) PRIMARY KEY, email VARCHAR(255), username VARCHAR(50),
    hashed_password VARCHAR(255), is_active BOOLEAN,
    created_at DATETIME, updated_at DATETIME
)
"""

LEGACY_RATE_LIMITS = """
CREATE TABLE rate_limits (
    id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), endpoint VARCHAR(255),
    requests_per_minute INTEGER, burst_capacity INTEGER, algorithm VARCHAR(20),
    created_at DATETIME, updated_at DATETIME
)
"""


def _recreate(table, ddl, *rows):
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE {table}"))
        conn.execute(text(ddl))
        for row in rows:
            conn.execute(text(row))


def test_upgrade_adds_the_admin_column_to_an_old_users_table():
    _recreate("users", LEGACY_USERS, "INSERT INTO users (id, username) VALUES ('u1', 'legacy')")

    setup_db.upgrade_schema()
    setup_db.upgrade_schema()  # and is safe to repeat

    assert "is_admin" in {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.connect() as conn:
        assert not conn.execute(text("SELECT is_admin FROM users WHERE id = 'u1'")).scalar()


def test_upgrade_enforces_one_rule_per_endpoint_on_an_old_table():
    _recreate("rate_limits", LEGACY_RATE_LIMITS)

    setup_db.upgrade_schema()

    insert = "INSERT INTO rate_limits (id, user_id, endpoint) VALUES ('{}', 'u1', '*')"
    with engine.begin() as conn:
        conn.execute(text(insert.format("r1")))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(insert.format("r2")))


def test_upgrade_tolerates_existing_duplicate_rules(caplog):
    """Refusing to start would be worse than running without the index."""
    _recreate(
        "rate_limits",
        LEGACY_RATE_LIMITS,
        "INSERT INTO rate_limits (id, user_id, endpoint) VALUES ('r1', 'u1', '*')",
        "INSERT INTO rate_limits (id, user_id, endpoint) VALUES ('r2', 'u1', '*')",
    )

    with caplog.at_level("WARNING"):
        setup_db.upgrade_schema()

    assert "one rate-limit rule per endpoint" in caplog.text


def test_upgrade_tolerates_losing_the_race_to_add_the_column(monkeypatch, caplog):
    """Two replicas can both see the column missing; the slower ALTER fails."""

    class StaleInspector:
        def get_columns(self, table):
            return []

    monkeypatch.setattr(setup_db, "inspect", lambda _engine: StaleInspector())

    with caplog.at_level("WARNING"):
        setup_db.upgrade_schema()

    assert "users.is_admin" in caplog.text


def test_the_seeded_admin_can_sign_in_and_read_its_profile(client, monkeypatch):
    """Regression: the old default address (admin@sentryflow.local) failed
    email validation, so /auth/me returned 500 and the dashboard logged the
    admin straight back out."""
    monkeypatch.setenv("SENTRYFLOW_ADMIN_PASSWORD", "admin-password")
    setup_db.create_admin_user()

    token = client.post(
        "/auth/login", data={"username": setup_db.ADMIN_USERNAME, "password": "admin-password"}
    ).json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert me.status_code == 200
    assert me.json()["is_admin"] is True


def test_profiles_with_a_legacy_email_still_load(client, user):
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == user["id"]).update({"email": "old@sentryflow.local"})
        db.commit()
    finally:
        db.close()

    me = client.get("/auth/me", headers=user["headers"])
    assert me.status_code == 200
    assert me.json()["email"] == "old@sentryflow.local"
