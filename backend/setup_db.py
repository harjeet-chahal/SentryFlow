"""Database bootstrap.

Creates the schema and seeds the minimum a fresh deployment needs: one admin
account and a default rate-limit rule. Every step is idempotent so this can
run on each deploy -- which is what the Kubernetes init job does.
"""
import argparse
import logging
import os
import secrets
from typing import Optional, Tuple

from passlib.context import CryptContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from backend.config import settings
from backend.models.database import SessionLocal, engine
from backend.models.models import Base, RateLimit, User

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ADMIN_USERNAME = os.getenv("SENTRYFLOW_ADMIN_USERNAME", "admin")
# Must pass email validation: reserved domains such as .local are rejected.
ADMIN_EMAIL = os.getenv("SENTRYFLOW_ADMIN_EMAIL", "admin@example.com")


def init_db() -> None:
    """Create any missing tables and bring older ones up to date. Safe to re-run."""
    Base.metadata.create_all(bind=engine)
    upgrade_schema()
    logger.info("Schema is up to date")


def upgrade_schema() -> None:
    """Apply the additive changes that ``create_all`` cannot.

    ``create_all`` only creates tables that are missing; it never alters one
    that exists. A database created before a column or index was added would
    otherwise fail on its first query. Both steps check before they act, and
    both tolerate losing a race with another replica doing the same thing.
    """
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    if "is_admin" not in columns:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE")
                )
            logger.info("Added users.is_admin")
        except SQLAlchemyError:
            logger.warning("Could not add users.is_admin; another replica may have", exc_info=True)

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rate_limits_user_endpoint "
                    "ON rate_limits (user_id, endpoint)"
                )
            )
    except SQLAlchemyError:
        # Existing duplicate rules block the index. The limiter still works
        # (it takes the first match), so warn rather than refuse to start.
        logger.warning("Could not enforce one rate-limit rule per endpoint", exc_info=True)


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
            if existing.is_admin:
                logger.info("Admin user already present")
            else:
                # Never promote automatically: an account with this name may
                # have come through public signup rather than from this script.
                logger.warning(
                    "User %r exists but is not an administrator. If it is yours, run "
                    "`python -m backend.setup_db --grant-admin %s`.",
                    ADMIN_USERNAME,
                    ADMIN_USERNAME,
                )
            return existing

        password, generated = _resolve_admin_password()
        admin = User(
            username=ADMIN_USERNAME,
            email=ADMIN_EMAIL,
            hashed_password=pwd_context.hash(password),
            is_active=True,
            is_admin=True,
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


def grant_admin(username: str, db=None) -> bool:
    """Make an existing user an administrator. Returns whether they exist."""
    own_session = db is None
    db = db or SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            logger.error("No user named %r", username)
            return False
        user.is_admin = True
        db.commit()
        logger.info("Granted admin role to %s", username)
        return True
    finally:
        if own_session:
            db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create or upgrade the SentryFlow schema.")
    parser.add_argument(
        "--grant-admin",
        metavar="USERNAME",
        help="also make an existing user an administrator",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    init_db()
    create_admin_user()
    setup_default_rate_limits()
    if args.grant_admin and not grant_admin(args.grant_admin):
        return 1
    logger.info("Database setup complete")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
