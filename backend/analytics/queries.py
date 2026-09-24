"""Analytics over the raw ``api_usage`` events in ClickHouse.

Everything is computed at query time from raw rows. ClickHouse scans them
fast enough at this scale, and raw rows keep latency percentiles honest: a
p95 cannot be derived from pre-aggregated p95s. If volume grows, the next
step is a materialized view keeping ``quantileState`` per bucket.

Two definitions hold throughout:

    errors        4xx and 5xx responses, excluding 429. Throttling is
                  reported separately as ``rate_limited``, so a noisy client
                  hitting its limit does not read as the API failing.
    latency       measured over served requests only. A 429 is turned away
                  before the handler runs, so it is far cheaper than a real
                  response; counting it would flatter every percentile.

Buckets are aligned to the Unix epoch, so they are UTC hours and UTC days.
Every series is zero-filled: one point per bucket, traffic or not.
"""
import asyncio
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.analytics.clickhouse import query

# range -> (bucket width in seconds, number of buckets)
RANGES = {
    "1h": (60, 60),
    "24h": (3600, 24),
    "7d": (6 * 3600, 28),
    "30d": (86400, 30),
}

TOP_N = 10
MAX_LOG_ROWS = 1000

_ERROR = "status_code >= 400 AND status_code != 429"
_SERVED = "status_code != 429"


@dataclass(frozen=True)
class Window:
    """A time range cut into equal buckets. Times are Unix seconds."""

    range_key: str
    step: int
    buckets: int
    start: int  # first bucket, inclusive
    end: int  # end of the current bucket, exclusive

    @property
    def bucket_starts(self) -> List[int]:
        return [self.start + i * self.step for i in range(self.buckets)]


def window_for(range_key: str, now: Optional[float] = None) -> Window:
    """The window ending with the bucket that contains ``now``.

    The newest bucket is still filling, so the chart's last point moves as
    traffic arrives. That is what makes the dashboard live.
    """
    step, buckets = RANGES[range_key]
    now = int(time.time() if now is None else now)
    current = now - now % step
    return Window(range_key, step, buckets, current - (buckets - 1) * step, current + step)


def _where(window: Window, user_id: Optional[str]) -> str:
    # Only constant fragments are interpolated; every value is a parameter.
    clause = "timestamp >= toDateTime(%(start)s) AND timestamp < toDateTime(%(end)s)"
    if user_id is not None:
        clause += " AND user_id = %(user_id)s"
    return clause


def _params(window: Window, user_id: Optional[str], **extra: Any) -> Dict[str, Any]:
    params = {"start": window.start, "end": window.end, "step": window.step, **extra}
    if user_id is not None:
        params["user_id"] = user_id
    return params


def _ms(value: Any) -> Optional[float]:
    """Latency for JSON. ClickHouse returns NaN when there was nothing to measure."""
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else round(value, 1)


def _percent(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

async def _summary(window: Window, user_id: Optional[str]) -> Dict[str, Any]:
    rows = await query(
        "summary",
        f"""
        SELECT
            count(),
            countIf({_ERROR}),
            countIf(status_code = 429),
            avgIf(response_time, {_SERVED}),
            quantilesIf(0.5, 0.95, 0.99)(response_time, {_SERVED})
        FROM api_usage
        WHERE {_where(window, user_id)}
        """,
        _params(window, user_id),
    )
    requests, errors, rate_limited, avg_ms, quantiles = rows[0] if rows else (0, 0, 0, None, [])
    p50, p95, p99 = (list(quantiles) + [None, None, None])[:3]
    return {
        "requests": requests,
        "errors": errors,
        "rate_limited": rate_limited,
        "error_rate": _percent(errors, requests),
        "rate_limited_rate": _percent(rate_limited, requests),
        "avg_ms": _ms(avg_ms),
        "p50_ms": _ms(p50),
        "p95_ms": _ms(p95),
        "p99_ms": _ms(p99),
    }


async def _series(window: Window, user_id: Optional[str]) -> List[Dict[str, Any]]:
    rows = await query(
        "series",
        f"""
        SELECT
            intDiv(toUnixTimestamp(timestamp), %(step)s) * %(step)s AS bucket,
            count(),
            countIf({_ERROR}),
            countIf(status_code = 429),
            avgIf(response_time, {_SERVED}),
            quantileIf(0.95)(response_time, {_SERVED})
        FROM api_usage
        WHERE {_where(window, user_id)}
        GROUP BY bucket
        ORDER BY bucket
        """,
        _params(window, user_id),
    )
    by_bucket = {int(row[0]): row for row in rows}

    series = []
    for t in window.bucket_starts:
        _, requests, errors, rate_limited, avg_ms, p95_ms = by_bucket.get(t, (t, 0, 0, 0, None, None))
        series.append(
            {
                "t": t,
                "requests": requests,
                "errors": errors,
                "rate_limited": rate_limited,
                "avg_ms": _ms(avg_ms),
                "p95_ms": _ms(p95_ms),
            }
        )
    return series


async def _status_codes(window: Window, user_id: Optional[str]) -> Dict[str, int]:
    rows = await query(
        "status_codes",
        f"""
        SELECT intDiv(status_code, 100) AS class, count()
        FROM api_usage
        WHERE {_where(window, user_id)}
        GROUP BY class
        """,
        _params(window, user_id),
    )
    counts = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
    for status_class, count in rows:
        key = f"{int(status_class)}xx"
        if key in counts:
            counts[key] = count
    return counts


async def _top_endpoints(window: Window, user_id: Optional[str]) -> List[Dict[str, Any]]:
    rows = await query(
        "top_endpoints",
        f"""
        SELECT
            endpoint,
            count() AS requests,
            countIf({_ERROR}),
            countIf(status_code = 429),
            quantileIf(0.95)(response_time, {_SERVED})
        FROM api_usage
        WHERE {_where(window, user_id)}
        GROUP BY endpoint
        ORDER BY requests DESC, endpoint
        LIMIT %(top_n)s
        """,
        _params(window, user_id, top_n=TOP_N),
    )
    return [
        {
            "endpoint": endpoint,
            "requests": requests,
            "errors": errors,
            "rate_limited": rate_limited,
            "p95_ms": _ms(p95_ms),
        }
        for endpoint, requests, errors, rate_limited, p95_ms in rows
    ]


async def _throttled_by(column: str, window: Window, user_id: Optional[str]) -> List[Dict[str, Any]]:
    # ``column`` is one of two literals chosen below, never caller input.
    assert column in ("endpoint", "user_id")
    rows = await query(
        f"throttled_by_{column}",
        f"""
        SELECT
            {column},
            count() AS requests,
            countIf(status_code = 429) AS rate_limited
        FROM api_usage
        WHERE {_where(window, user_id)}
        GROUP BY {column}
        HAVING rate_limited > 0
        ORDER BY rate_limited DESC, {column}
        LIMIT %(top_n)s
        """,
        _params(window, user_id, top_n=TOP_N),
    )
    return [
        {column: key, "requests": requests, "rate_limited": rate_limited}
        for key, requests, rate_limited in rows
    ]


# ---------------------------------------------------------------------------
# What the endpoints return
# ---------------------------------------------------------------------------

async def usage(window: Window, user_id: Optional[str]) -> Dict[str, Any]:
    """Headline numbers, time series, status mix and busiest endpoints."""
    summary, series, status_codes, top_endpoints = await asyncio.gather(
        _summary(window, user_id),
        _series(window, user_id),
        _status_codes(window, user_id),
        _top_endpoints(window, user_id),
    )
    return {
        "summary": summary,
        "series": series,
        "status_codes": status_codes,
        "top_endpoints": top_endpoints,
    }


async def rate_limits(window: Window, user_id: Optional[str], include_users: bool) -> Dict[str, Any]:
    """Allowed versus throttled over time, and where the throttling lands."""
    tasks = [_series(window, user_id), _throttled_by("endpoint", window, user_id)]
    if include_users:
        tasks.append(_throttled_by("user_id", window, user_id))
    results = await asyncio.gather(*tasks)
    series, by_endpoint = results[0], results[1]
    by_user = results[2] if include_users else []

    requests = sum(point["requests"] for point in series)
    rate_limited = sum(point["rate_limited"] for point in series)
    return {
        "totals": {
            "requests": requests,
            "rate_limited": rate_limited,
            "rate_limited_rate": _percent(rate_limited, requests),
        },
        "series": [
            {
                "t": point["t"],
                "allowed": point["requests"] - point["rate_limited"],
                "rate_limited": point["rate_limited"],
            }
            for point in series
        ],
        "by_endpoint": by_endpoint,
        "by_user": by_user,
    }


async def logs(
    window: Window,
    user_id: Optional[str],
    status_class: Optional[int],
    endpoint: Optional[str],
    limit: int,
) -> Dict[str, Any]:
    """The newest matching requests, newest first."""
    where = _where(window, user_id)
    extra: Dict[str, Any] = {"limit": limit + 1}
    if status_class is not None:
        where += " AND intDiv(status_code, 100) = %(status_class)s"
        extra["status_class"] = status_class
    if endpoint:
        where += " AND positionCaseInsensitive(endpoint, %(endpoint)s) > 0"
        extra["endpoint"] = endpoint

    rows = await query(
        "logs",
        f"""
        SELECT toUnixTimestamp(timestamp), user_id, endpoint, status_code, response_time
        FROM api_usage
        WHERE {where}
        ORDER BY timestamp DESC
        LIMIT %(limit)s
        """,
        _params(window, user_id, **extra),
    )
    # One extra row was requested to learn whether there were more.
    return {
        "truncated": len(rows) > limit,
        "rows": [
            {
                "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "user_id": uid,
                "endpoint": path,
                "status_code": status_code,
                "response_time_ms": response_time,
            }
            for ts, uid, path, status_code, response_time in rows[:limit]
        ],
    }


async def per_user(window: Window) -> Dict[str, Dict[str, Any]]:
    """Traffic per user in the window, keyed by user id."""
    rows = await query(
        "per_user",
        f"""
        SELECT
            user_id,
            count(),
            countIf({_ERROR}),
            countIf(status_code = 429),
            quantileIf(0.95)(response_time, {_SERVED}),
            toUnixTimestamp(max(timestamp))
        FROM api_usage
        WHERE {_where(window, None)}
        GROUP BY user_id
        """,
        _params(window, None),
    )
    return {
        user_id: {
            "requests": requests,
            "errors": errors,
            "rate_limited": rate_limited,
            "p95_ms": _ms(p95_ms),
            "last_seen": last_seen,
        }
        for user_id, requests, errors, rate_limited, p95_ms, last_seen in rows
    }
