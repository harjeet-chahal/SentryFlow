from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import uvicorn
import time

from backend.auth import auth_router
from backend.middlewares.auth_middleware import verify_api_key
from backend.middlewares.logging_middleware import log_request
from backend.limiter.rate_limiter import check_rate_limit
from backend.models import database, models

# Initialize FastAPI app
app = FastAPI(
    title="SentryFlow API Gateway",
    description="A scalable API Gateway with rate limiting and usage analytics",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router.router, prefix="/auth", tags=["Authentication"])

# Create database tables
models.Base.metadata.create_all(bind=database.engine)


# Dependency to get DB session
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Middleware for API key verification, rate limiting, and request logging
@app.middleware("http")
async def middleware(request: Request, call_next):
    # Skip middleware for auth routes
    if request.url.path.startswith("/auth"):
        return await call_next(request)
    
    # Verify API key
    api_key = request.headers.get("x-api-key")
    if not api_key:
        return Response(status_code=401, content="API key is required")
    
    # Get user_id from API key
    user_id = await verify_api_key(api_key)
    if not user_id:
        return Response(status_code=401, content="Invalid API key")
    
    # Check rate limit
    endpoint = request.url.path
    is_allowed, remaining = await check_rate_limit(user_id, endpoint)
    if not is_allowed:
        # Log rate limited event to Kafka
        await log_request(user_id, endpoint, 429, 0)
        return Response(
            status_code=429, 
            content="Rate limit exceeded",
            headers={"X-RateLimit-Remaining": str(remaining)}
        )
    
    # Process the request
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    # Log successful request to Kafka
    await log_request(user_id, endpoint, response.status_code, int(process_time * 1000))
    
    # Add rate limit headers
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    
    return response


# Sample protected endpoint
@app.get("/api/v1/hello")
async def hello_world():
    return {"message": "Hello from SentryFlow!"}


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)