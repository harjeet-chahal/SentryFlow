"""Database bootstrap: schema creation and idempotent seeding."""
import pytest

from backend import setup_db
from backend.config import settings
from backend.models.database import SessionLocal
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
    setup_db.main()

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.username == setup_db.ADMIN_USERNAME).count() == 1
        assert db.query(RateLimit).filter(RateLimit.endpoint == "*").count() == 1
    finally:
        db.close()
