"""Rate-limit rules, managed from the dashboard.

Anyone signed in can read the rules that apply to them; only administrators
can change them. A customer who could edit their own limit would not really
have one.

A rule applies to one user on one endpoint, or on every endpoint (``*``).
The gateway resolves a request by exact endpoint, then the user's ``*`` rule,
then the global defaults, and caches that resolution in Redis. Every write
here evicts the cache, so a change applies on the next request.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.auth_router import get_current_admin, get_current_user, get_db, scoped_user_id
from backend.config import settings
from backend.limiter.rate_limiter import default_config, invalidate_config_cache
from backend.limiter.schemas import RateLimitRuleIn, RateLimitRuleOut, RateLimitRules
from backend.models.models import RateLimit, User

router = APIRouter()


def _to_out(rule: RateLimit, username: Optional[str]) -> RateLimitRuleOut:
    return RateLimitRuleOut(
        id=rule.id,
        user_id=rule.user_id,
        username=username,
        endpoint=rule.endpoint,
        requests_per_minute=rule.requests_per_minute,
        burst_capacity=rule.burst_capacity,
        algorithm=rule.algorithm,
        updated_at=rule.updated_at or rule.created_at,
    )


@router.get("", response_model=RateLimitRules)
async def list_rules(
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The rules in force, plus the defaults for callers without one."""
    scope = scoped_user_id(current_user, user_id)

    query = db.query(RateLimit, User.username).join(User, User.id == RateLimit.user_id)
    if scope is not None:
        query = query.filter(RateLimit.user_id == scope)
    rows = query.order_by(User.username, RateLimit.endpoint).all()

    return RateLimitRules(
        defaults={**default_config(), "window_seconds": settings.DEFAULT_RATE_LIMIT_WINDOW},
        rules=[_to_out(rule, username) for rule, username in rows],
    )


@router.put("", response_model=RateLimitRuleOut)
async def upsert_rule(
    body: RateLimitRuleIn,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Create the rule for (user, endpoint), or replace it if one exists."""
    user = db.query(User).filter(User.id == body.user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    rule = (
        db.query(RateLimit)
        .filter(RateLimit.user_id == body.user_id, RateLimit.endpoint == body.endpoint)
        .first()
    )
    if rule is None:
        rule = RateLimit(user_id=body.user_id, endpoint=body.endpoint)
        db.add(rule)

    rule.requests_per_minute = body.requests_per_minute
    rule.burst_capacity = body.burst_capacity
    rule.algorithm = body.algorithm
    rule.updated_at = datetime.utcnow()

    try:
        db.commit()
    except IntegrityError:
        # Another admin created the same rule between our read and write.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The rule was changed at the same time; retry",
        )
    db.refresh(rule)

    await invalidate_config_cache(body.user_id)
    return _to_out(rule, user.username)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Remove a rule; the user falls back to their next match or the defaults."""
    rule = db.query(RateLimit).filter(RateLimit.id == rule_id).first()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    user_id = rule.user_id
    db.delete(rule)
    db.commit()

    await invalidate_config_cache(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
