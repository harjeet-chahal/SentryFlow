"""SentryFlow API gateway.

Every request outside the API-key-exempt paths passes through one
middleware chain: resolve the API key to a user, apply that user's rate
limit, serve the request, then emit a usage event to Kafka. The ordering
matters -- an unauthenticated caller must be rejected before it can consume
another caller's rate-limit budget.

The dashboard's own APIs (``/auth``, ``/analytics``, ``/limits``) sit
outside that chain: they authenticate a person with a JWT, per route.
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend import health_check
from backend.analytics import analytics_router
from backend.analytics.clickhouse import AnalyticsUnavailable, close_all as close_clickhouse
from backend.auth import auth_router
from backend.config import settings
from backend.limiter import limits_router
from backend.limiter.rate_limiter import check_rate_limit
from backend.middlewares.auth_middleware import verify_api_key
from backend.middlewares.logging_middleware import log_request, shutdown as stop_producer, start_producer
from backend.redis_client import close_redis
from backend.setup_db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths that take no API key. Probes are here because kubelet cannot present
# credentials; docs so the gateway is explorable. The dashboard APIs are here
# because they authenticate a person with a JWT instead, route by route --
# exempt from the API key, not open.
API_KEY_EXEMPT_PREFIXES = ("/auth", "/health", "/analytics", "/limits")
API_KEY_EXEMPT_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect", "/"})


def is_api_key_exempt(path: str) -> bool:
    """Whether a path bypasses API-key enforcement.

    Matching is on whole path segments. A bare ``startswith`` would also
    exempt ``/healthz`` or ``/authorize``, silently opening any route whose
    name merely begins with an exempt prefix.
    """
    if path in API_KEY_EXEMPT_PATHS:
        return True
    return any(
        path == prefix or path.startswith(prefix + "/") for prefix in API_KEY_EXEMPT_PREFIXES
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own the lifecycle of connections shared across requests."""
    init_db()
    await start_producer()
    try:
        yield
    finally:
        await stop_producer()
        await close_redis()
        close_clickhouse()


app = FastAPI(
    title="SentryFlow API Gateway",
    description="API gateway with distributed rate limiting and usage analytics",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/auth", tags=["Authentication"])
app.include_router(analytics_router.router, prefix="/analytics", tags=["Analytics"])
app.include_router(limits_router.router, prefix="/limits", tags=["Rate limits"])
app.include_router(health_check.router)


@app.exception_handler(AnalyticsUnavailable)
async def analytics_unavailable(request: Request, exc: AnalyticsUnavailable):
    """The dashboard degrades; the gateway itself does not depend on ClickHouse."""
    return JSONResponse(status_code=503, content={"detail": "Analytics store unavailable"})


def _elapsed_ms(started: float) -> int:
    # Rounded, not truncated: truncation turns every sub-millisecond request
    # into 0 and drags averages and percentiles down.
    return round((time.perf_counter() - started) * 1000)


@app.middleware("http")
async def gateway_middleware(request: Request, call_next):
    """Authenticate, rate limit, serve, then record usage.

    The recorded response time covers the whole gateway path -- key lookup,
    limit check and handler -- because that is the latency callers see.
    """
    if is_api_key_exempt(request.url.path):
        return await call_next(request)

    started = time.perf_counter()
    api_key = request.headers.get("x-api-key")
    if not api_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing API key. Supply it in the x-api-key header."},
        )

    user_id = await verify_api_key(api_key)
    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "Invalid or revoked API key."})

    endpoint = request.url.path
    result = await check_rate_limit(user_id, endpoint)

    if not result.allowed:
        # Record the rejection so throttling shows up in analytics.
        await log_request(user_id, endpoint, 429, _elapsed_ms(started))
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded."},
            headers=result.headers,
        )

    response = await call_next(request)
    await log_request(user_id, endpoint, response.status_code, _elapsed_ms(started))

    for header, value in result.headers.items():
        response.headers[header] = value

    return response


@app.get("/api/v1/hello", tags=["Demo"])
async def hello_world():
    """Minimal protected endpoint, used to exercise the gateway path."""
    return {"message": "Hello from SentryFlow!"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
