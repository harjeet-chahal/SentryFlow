"""Usage and latency analytics for the dashboard.

These endpoints authenticate a person (JWT), not a machine (API key), and
scope what they return: an administrator sees every user's traffic, or one
user's on request; anyone else sees only their own.

They await ClickHouse, so they are async; their own database lookups go to
the threadpool rather than stall the event loop.
"""
from typing import Dict, Iterable, List, Literal, Optional, Set

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.analytics import queries
from backend.auth.auth_router import get_current_admin, get_current_user, get_db, scoped_user_id
from backend.models.models import User

router = APIRouter()

TimeRange = Literal["1h", "24h", "7d", "30d"]
StatusClass = Literal["all", "2xx", "3xx", "4xx", "5xx"]

_RANGE = Query("24h", alias="range", description="1h, 24h, 7d or 30d")


def _query_usernames(db: Session, ids: Set[str]) -> Dict[str, str]:
    return dict(db.query(User.id, User.username).filter(User.id.in_(ids)).all())


async def _usernames(db: Session, user_ids: Iterable[Optional[str]]) -> Dict[str, str]:
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    return await run_in_threadpool(_query_usernames, db, ids)


async def _scope(db: Session, user_id: Optional[str]) -> dict:
    names = await _usernames(db, [user_id])
    return {"user_id": user_id, "username": names.get(user_id)}


async def _with_usernames(db: Session, rows: List[dict]) -> List[dict]:
    names = await _usernames(db, (row["user_id"] for row in rows))
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
    return {"range": range_, "step_seconds": window.step, "scope": await _scope(db, scope), **data}


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
    data["by_user"] = await _with_usernames(db, data["by_user"])
    return {"range": range_, "step_seconds": window.step, "scope": await _scope(db, scope), **data}


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
        "rows": await _with_usernames(db, data["rows"]),
    }


def _accounts(db: Session, ids: List[str]) -> Dict[str, dict]:
    users = db.query(User).filter(User.id.in_(ids)).all() if ids else []
    return {
        user.id: {
            "username": user.username,
            "email": user.email,
            "is_active": bool(user.is_active),
            "is_admin": bool(user.is_admin),
        }
        for user in users
    }


# Traffic outlives the account it came from.
_DELETED = {"username": None, "email": None, "is_active": False, "is_admin": False}


@router.get("/users")
async def users(
    range_: TimeRange = _RANGE,
    limit: int = Query(50, ge=1, le=queries.MAX_USERS_PAGE),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Users with traffic in the range, busiest first, a page at a time.

    Administrators only. ``total`` counts every user with traffic. Accounts
    without any are not listed; ``/auth/users`` lists every account.
    """
    window = queries.window_for(range_)
    page = await queries.top_users(window, limit, offset)
    accounts = await run_in_threadpool(_accounts, db, [row["user_id"] for row in page["users"]])

    listed = []
    for row in page["users"]:
        stats = dict(row)
        user_id = stats.pop("user_id")
        listed.append({"id": user_id, **accounts.get(user_id, _DELETED), **stats})
    return {"range": range_, "total": page["total"], "limit": limit, "offset": offset, "users": listed}
