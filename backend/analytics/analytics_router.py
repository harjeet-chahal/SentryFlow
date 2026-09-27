"""Usage and latency analytics for the dashboard.

These endpoints authenticate a person (JWT), not a machine (API key), and
scope what they return: an administrator sees every user's traffic, or one
user's on request; anyone else sees only their own.
"""
from typing import Dict, Iterable, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.analytics import queries
from backend.auth.auth_router import get_current_admin, get_current_user, get_db, scoped_user_id
from backend.models.models import User

router = APIRouter()

TimeRange = Literal["1h", "24h", "7d", "30d"]
StatusClass = Literal["all", "2xx", "3xx", "4xx", "5xx"]

_RANGE = Query("24h", alias="range", description="1h, 24h, 7d or 30d")


def _usernames(db: Session, user_ids: Iterable[str]) -> Dict[str, str]:
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    return dict(db.query(User.id, User.username).filter(User.id.in_(ids)).all())


def _scope(db: Session, user_id: Optional[str]) -> dict:
    return {"user_id": user_id, "username": _usernames(db, [user_id]).get(user_id) if user_id else None}


def _with_usernames(db: Session, rows: List[dict]) -> List[dict]:
    names = _usernames(db, (row["user_id"] for row in rows))
    return [{**row, "username": names.get(row["user_id"])} for row in rows]


@router.get("/usage")
async def usage(
    range_: TimeRange = _RANGE,
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Request volume, errors, throttling and latency over a time range."""
    scope = scoped_user_id(current_user, user_id)
    window = queries.window_for(range_)
    data = await queries.usage(window, scope)
    return {"range": range_, "step_seconds": window.step, "scope": _scope(db, scope), **data}


@router.get("/rate-limits")
async def rate_limits(
    range_: TimeRange = _RANGE,
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Allowed versus throttled requests, and who and what is being throttled."""
    scope = scoped_user_id(current_user, user_id)
    window = queries.window_for(range_)
    # Ranking users only makes sense when looking across all of them.
    data = await queries.rate_limits(window, scope, include_users=scope is None)
    data["by_user"] = _with_usernames(db, data["by_user"])
    return {"range": range_, "step_seconds": window.step, "scope": _scope(db, scope), **data}


@router.get("/logs")
async def request_logs(
    range_: TimeRange = Query("1h", alias="range", description="1h, 24h, 7d or 30d"),
    status: StatusClass = "all",
    endpoint: Optional[str] = Query(None, max_length=255, description="Substring, case-insensitive"),
    user_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=queries.MAX_LOG_ROWS),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The most recent requests matching the filters, newest first."""
    scope = scoped_user_id(current_user, user_id)
    window = queries.window_for(range_)
    status_class = None if status == "all" else int(status[0])
    data = await queries.logs(window, scope, status_class, endpoint or None, limit)
    return {
        "range": range_,
        "limit": limit,
        "truncated": data["truncated"],
        "rows": _with_usernames(db, data["rows"]),
    }


@router.get("/users")
async def users(
    range_: TimeRange = _RANGE,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Every account with its traffic in the range. Administrators only."""
    window = queries.window_for(range_)
    stats = await queries.per_user(window)
    idle = {"requests": 0, "errors": 0, "rate_limited": 0, "p95_ms": None, "last_seen": None}

    accounts = [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": bool(user.is_active),
            "is_admin": bool(user.is_admin),
            **stats.get(user.id, idle),
        }
        for user in db.query(User).all()
    ]
    accounts.sort(key=lambda account: (-account["requests"], account["username"] or ""))
    return {"range": range_, "users": accounts}
