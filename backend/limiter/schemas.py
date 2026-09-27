"""Request and response bodies for rate-limit rules."""
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, validator

Algorithm = Literal["sliding_window", "token_bucket"]


class RateLimitRuleIn(BaseModel):
    """Create or replace the rule for one (user, endpoint) pair."""

    user_id: str = Field(..., min_length=1, max_length=36)
    endpoint: str = Field(
        "*",
        min_length=1,
        max_length=255,
        description='"*" for every endpoint, or an exact request path such as /api/v1/hello',
    )
    requests_per_minute: int = Field(..., ge=1, le=1_000_000)
    burst_capacity: int = Field(10, ge=1, le=1_000_000, description="Token bucket only")
    algorithm: Algorithm = "sliding_window"

    @validator("endpoint")
    def endpoint_is_wildcard_or_path(cls, value: str) -> str:
        value = value.strip()
        if value != "*" and not value.startswith("/"):
            raise ValueError('must be "*" or a path starting with "/"')
        return value


class RateLimitRuleOut(BaseModel):
    id: str
    user_id: str
    username: Optional[str]
    endpoint: str
    requests_per_minute: int
    burst_capacity: int
    algorithm: str
    updated_at: datetime

    @validator("updated_at")
    def mark_as_utc(cls, value: datetime) -> datetime:
        # Stored naive in UTC. Without an offset, browsers read it as local time.
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class RateLimitDefaults(BaseModel):
    """What applies to a caller with no matching rule."""

    requests_per_minute: int
    burst_capacity: int
    algorithm: str
    window_seconds: int


class RateLimitRules(BaseModel):
    defaults: RateLimitDefaults
    rules: List[RateLimitRuleOut]
