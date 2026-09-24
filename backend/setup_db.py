"""Database bootstrap.

Creates the schema and seeds the minimum a fresh deployment needs: one admin
account and a default rate-limit rule. Every step is idempotent so this can
run on each deploy -- which is what the Kubernetes init job does.
"""
import logging
import os
import secrets
from typing import Optional, Tuple

from passlib.context import CryptContext

from backend.config import settings
from backend.models.database import SessionLocal, engine
from backend.models.models import Base, RateLimit, User

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ADMIN_USERNAME = os.getenv("SENTRYFLOW_ADMIN_USERNAME", "admin")
ADMIN_EMAIL = os.getenv("SENTRYFLOW_ADMIN_EMAIL", "admin@sentryflow.local")


def init_db() -> None:
    """Create any missing tables. Safe to re-run."""
    Base.metadata.create_all(bind=engine)
    logger.info("Schema is up to date")


def _resolve_admin_password() -> Tuple[str, bool]:
    """Return the admin password and whether it was generated.

    A generated password is printed once and never stored in plaintext, so a
    fresh deploy is usable without shipping a default credential in source.
    """
    supplied = os.getenv("SENTRYFLOW_ADMIN_PASSWORD")
    if supplied:
        return supplied, False
    return secrets.token_urlsafe(24), True


def create_admin_user(db=None) -> Optional[User]:
    """Create the admin account if it is absent. Returns it either way."""
    own_session = db is None
    db = db or SessionLocal()
    try:
        existing = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if existing:
            logger.info("Admin user already present")
            return existing

        password, generated = _resolve_admin_password()
        admin = User(
            username=ADMIN_USERNAME,
            email=ADMIN_EMAIL,
            hashed_password=pwd_context.hash(password),
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        if generated:
            # Printed, never persisted. Rotate it after first login.
            print(f"Generated admin password for '{ADMIN_USERNAME}': {password}")
        logger.info("Created admin user %s", ADMIN_USERNAME)
        return admin
    finally:
        if own_session:
            db.close()


def setup_default_rate_limits(db=None) -> Optional[RateLimit]:
    """Seed the admin's catch-all rate limit if it is absent."""
    own_session = db is None
    db = db or SessionLocal()
    try:
        admin = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if admin is None:
            logger.warning("No admin user; skipping default rate limit")
            return None

        existing = (
            db.query(RateLimit)
            .filter(RateLimit.user_id == admin.id, RateLimit.endpoint == "*")
            .first()
        )
        if existing:
            logger.info("Default rate limit already present")
            return existing

        rule = RateLimit(
            user_id=admin.id,
            endpoint="*",
            requests_per_minute=settings.DEFAULT_REQUESTS_PER_MINUTE,
            burst_capacity=settings.DEFAULT_BURST_CAPACITY,
            algorithm=settings.DEFAULT_ALGORITHM,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        logger.info("Seeded default rate limit")
        return rule
    finally:
        if own_session:
            db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    create_admin_user()
    setup_default_rate_limits()
    logger.info("Database setup complete")


if __name__ == "__main__":  # pragma: no cover
    main()
