"""SentryFlow API gateway.

Every request outside the exempt paths passes through one middleware
chain: verify the caller's gateway token (a JWT naming the user), apply
that user's rate limit, serve the request, then emit a usage event to Kafka.
The ordering matters -- an unauthenticated caller must be rejected before it
can consume another caller's rate-limit budget.

The dashboard's own APIs (``/auth``, ``/analytics``, ``/limits``) sit
outside that chain: they authenticate a person with a dashboard JWT, per
route. ``/auth/token`` is where programs trade an API key for a gateway
token.
"""
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

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
from backend.middlewares.auth_middleware import verify_gateway_token
from backend.middlewares.logging_middleware import log_request, shutdown as stop_producer, start_producer
from backend.redis_client import close_redis
from backend.setup_db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths that bypass the gateway chain: no gateway token, rate limit or usage
# event. Probes are here because kubelet cannot present credentials; docs so
# the gateway is explorable; /auth because that is where tokens come from.
# The dashboard APIs authenticate a person with a dashboard JWT instead,
# route by route -- exempt from the gateway, not open.
GATEWAY_EXEMPT_PREFIXES = ("/auth", "/health", "/analytics", "/limits")
GATEWAY_EXEMPT_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect", "/"})


def is_gateway_exempt(path: str) -> bool:
    """Whether a path bypasses the gateway chain.

    Matching is on whole path segments. A bare ``startswith`` would also
    exempt ``/healthz`` or ``/authorize``, silently opening any route whose
    name merely begins with an exempt prefix.
    """
    if path in GATEWAY_EXEMPT_PATHS:
        return True
    return any(
        path == prefix or path.startswith(prefix + "/") for prefix in GATEWAY_EXEMPT_PREFIXES
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


def _bearer_token(request: Request) -> Optional[str]:
    """The token in an ``Authorization: Bearer <token>`` header, if any."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _elapsed_ms(started: float) -> int:
    # Rounded, not truncated: truncation turns every sub-millisecond request
    # into 0 and drags averages and percentiles down.
    return round((time.perf_counter() - started) * 1000)


@app.middleware("http")
async def gateway_middleware(request: Request, call_next):
    """Authenticate, rate limit, serve, then record usage.

    The recorded response time covers the whole gateway path -- token check,
    limit check and handler -- because that is the latency callers see.
    """
    if is_gateway_exempt(request.url.path):
        return await call_next(request)

    started = time.perf_counter()
    token = _bearer_token(request)
    if token is None:
        # RFC 6750: a 401 from a bearer-token resource names the scheme.
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Missing bearer token. Trade an API key for one at POST /auth/token, "
                "then send it as Authorization: Bearer <token>."
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = await verify_gateway_token(token)
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid, expired or revoked token."},
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    endpoint = request.url.path
    result = await check_rate_limit(user_id, endpoint)

    if not result.allowed:
        # Record the rejection so throttling shows up in analytics.
        log_request(user_id, endpoint, 429, _elapsed_ms(started))
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded."},
            headers=result.headers,
        )

    response = await call_next(request)
    log_request(user_id, endpoint, response.status_code, _elapsed_ms(started))

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
