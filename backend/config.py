"""Centralised configuration for the SentryFlow gateway.

Every tunable is read from the environment exactly once, here, so that the
rest of the codebase never calls ``os.getenv`` directly. This keeps the
twelve-factor contract in one auditable place and gives tests a single seam
to override.
"""
import os
import secrets
import logging

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


class Settings:
    """Runtime settings resolved from the environment."""

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # Storage / transport
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./sentryflow.db")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    # Kafka topics
    API_REQUESTS_TOPIC: str = os.getenv("API_REQUESTS_TOPIC", "api-requests")
    RATE_LIMITED_TOPIC: str = os.getenv("RATE_LIMITED_TOPIC", "rate-limited-events")

    # Auth
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    API_KEY_CACHE_TTL: int = int(os.getenv("API_KEY_CACHE_TTL", "3600"))

    # Rate limiting defaults, used when a user has no per-endpoint override
    DEFAULT_REQUESTS_PER_MINUTE: int = int(os.getenv("DEFAULT_RATE_LIMIT", "60"))
    DEFAULT_RATE_LIMIT_WINDOW: int = int(os.getenv("DEFAULT_RATE_LIMIT_WINDOW", "60"))
    DEFAULT_BURST_CAPACITY: int = int(os.getenv("DEFAULT_BURST_CAPACITY", "10"))
    DEFAULT_ALGORITHM: str = os.getenv("DEFAULT_RATE_LIMIT_ALGORITHM", "sliding_window")

    # Fail open (serve the request) or closed (reject) when Redis is unreachable.
    # Defaults to open: a rate limiter outage should not become an API outage.
    RATE_LIMIT_FAIL_OPEN: bool = _env_bool("RATE_LIMIT_FAIL_OPEN", True)

    CORS_ORIGINS: list = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
    ]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in ("production", "prod")


settings = Settings()


def _resolve_jwt_secret() -> str:
    """Resolve the JWT signing key.

    In production an explicit ``JWT_SECRET`` is mandatory -- we refuse to boot
    without one rather than silently signing tokens with a guessable constant.
    In development we mint an ephemeral random key so that a fresh checkout
    just works, at the cost of invalidating tokens on restart.
    """
    secret = os.getenv("JWT_SECRET")
    if secret:
        return secret
    if settings.is_production:
        raise RuntimeError(
            "JWT_SECRET must be set when ENVIRONMENT=production. Refusing to "
            "start with an ephemeral signing key."
        )
    logger.warning(
        "JWT_SECRET is unset; generating an ephemeral development key. "
        "Tokens will not survive a restart."
    )
    return secrets.token_urlsafe(48)


JWT_SECRET = _resolve_jwt_secret()
