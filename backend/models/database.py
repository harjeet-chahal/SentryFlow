"""Database engine and session factory.

The declarative ``Base`` lives in ``models.py`` and is re-exported here so
that either import path resolves to the same metadata. Two separate
``declarative_base()`` calls would silently give two registries, and
``create_all`` would then only create half the schema.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.models.models import Base  # noqa: F401 - re-exported for convenience

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    # SQLite is the zero-setup default for local runs and tests.
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        # Validate a connection before handing it out. Without this, every
        # RDS failover or idle-timeout reaping surfaces as a burst of
        # "server closed the connection unexpectedly" errors.
        pool_pre_ping=True,
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
