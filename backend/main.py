"""SentryFlow API gateway.

Every request that is not on the public allow-list passes through one
middleware chain: resolve the API key to a user, apply that user's rate
limit, serve the request, then emit a usage event to Kafka. The ordering
matters -- an unauthenticated caller must be rejected before it can consume
another caller's rate-limit budget.
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend import health_check
from backend.auth import auth_router
from backend.config import settings
from backend.limiter.rate_limiter import check_rate_limit
from backend.middlewares.auth_middleware import verify_api_key
from backend.middlewares.logging_middleware import log_request, shutdown as stop_producer, start_producer
from backend.models import database, models
from backend.redis_client import close_redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths served without an API key. Probes are here because kubelet cannot
# present credentials; docs are here so the gateway is explorable.
PUBLIC_PATH_PREFIXES = ("/auth", "/health")
PUBLIC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect", "/"})


def is_public_path(path: str) -> bool:
    """Whether a path bypasses API-key enforcement.

    Matching is on whole path segments. A bare ``startswith`` would also
    exempt ``/healthz`` or ``/authorize``, silently opening any route whose
    name merely begins with a public prefix.
    """
    if path in PUBLIC_PATHS:
        return True
    return any(
        path == prefix or path.startswith(prefix + "/") for prefix in PUBLIC_PATH_PREFIXES
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own the lifecycle of connections shared across requests."""
    models.Base.metadata.create_all(bind=database.engine)
    await start_producer()
    try:
        yield
    finally:
        await stop_producer()
        await close_redis()


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
app.include_router(health_check.router)


@app.middleware("http")
async def gateway_middleware(request: Request, call_next):
    """Authenticate, rate limit, serve, then record usage."""
    if is_public_path(request.url.path):
        return await call_next(request)

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
        # Record the rejection so throttling shows up in analytics. The
        # request never reached the handler, so its service time is zero.
        await log_request(user_id, endpoint, 429, 0)
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded."},
            headers=result.headers,
        )

    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    await log_request(user_id, endpoint, response.status_code, elapsed_ms)

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
