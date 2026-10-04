"""Health, readiness and liveness endpoints.

These are three different questions and Kubernetes treats them differently,
so they are deliberately not the same check:

    /health/live   Is this process alive? Touches no dependency. A liveness
                   probe that checked Redis would restart every pod in the
                   fleet during a Redis blip -- turning a degraded dependency
                   into a full outage.

    /health/ready  Can this pod serve traffic right now? Checks only the
                   dependencies required to answer a request: Postgres and
                   Redis. A failure pulls the pod out of the Service's
                   endpoints without restarting it, so it can rejoin when the
                   dependency recovers.

    /health        Operator-facing detail: per-component status and timings,
                   including non-critical dependencies. Not used as a probe.

Kafka is deliberately non-critical. Requests only queue their usage events
and a background task publishes them, so the gateway can authenticate, rate
limit and serve while Kafka is down; that state is reported as "degraded"
rather than failing readiness. The task reconnects on its own, so there is
nothing a restart would fix.
"""
import logging
import time
from typing import Any, Dict

from fastapi import APIRouter, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text

from backend.middlewares import logging_middleware
from backend.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])


def _check_database_sync() -> None:
    """Round-trip the database. Raises if it is unreachable."""
    from backend.models.database import SessionLocal

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()


async def _timed(coro_or_none) -> Dict[str, Any]:
    """Run a check, returning its status and how long it took."""
    started = time.perf_counter()
    try:
        await coro_or_none
        return {
            "status": "healthy",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:  # noqa: BLE001 - a health check reports, never raises
        logger.warning("Health check failed: %s", exc, exc_info=True)
        return {
            "status": "unhealthy",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(exc),
        }


async def check_database() -> Dict[str, Any]:
    return await _timed(run_in_threadpool(_check_database_sync))


async def check_redis() -> Dict[str, Any]:
    return await _timed(get_redis().ping())


async def check_kafka() -> Dict[str, Any]:
    """Report whether usage events are reaching Kafka.

    Built from what the publisher has seen rather than a broker round-trip:
    whether it is connected, and whether its latest delivery succeeded. The
    counters say how many events are waiting and how many were lost.
    """
    publisher = logging_middleware.status()
    counts = {key: publisher[key] for key in ("queued", "dropped", "failed")}
    if not publisher["connected"]:
        return {"status": "unavailable", "detail": "Connecting to Kafka", **counts}
    if not publisher["delivering"]:
        return {"status": "unavailable", "detail": "Kafka is not accepting events", **counts}
    return {"status": "healthy", **counts}


@router.get("", summary="Full system health")
async def health(response: Response) -> Dict[str, Any]:
    """Report per-component health. 503 when a critical dependency is down."""
    started = time.perf_counter()

    database = await check_database()
    redis_component = await check_redis()
    kafka = await check_kafka()

    critical_down = any(
        component["status"] != "healthy" for component in (database, redis_component)
    )
    if critical_down:
        overall = "unhealthy"
    elif kafka["status"] != "healthy":
        overall = "degraded"
    else:
        overall = "healthy"

    if critical_down:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": overall,
        "components": {
            "database": database,
            "redis": redis_component,
            "kafka": kafka,
        },
        "response_time_ms": round((time.perf_counter() - started) * 1000, 2),
    }


@router.get("/ready", summary="Readiness probe")
async def readiness(response: Response) -> Dict[str, Any]:
    """Check only what is needed to serve a request: Postgres and Redis."""
    database = await check_database()
    redis_component = await check_redis()

    ready = database["status"] == "healthy" and redis_component["status"] == "healthy"
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if ready else "not_ready",
        "checks": {"database": database, "redis": redis_component},
    }


@router.get("/live", summary="Liveness probe")
async def liveness() -> Dict[str, Any]:
    """Confirm the process is running. Intentionally checks nothing else."""
    return {"status": "alive"}
