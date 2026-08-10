import redis
import os
from typing import Optional
from sqlalchemy.orm import Session
from backend.models.database import SessionLocal
from backend.models.models import ApiKey

# Redis connection for caching API keys
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Cache TTL for API keys (1 hour)
API_KEY_CACHE_TTL = 3600


async def verify_api_key(api_key: str) -> Optional[str]:
    """Verify an API key and return the associated user_id if valid.
    
    Args:
        api_key: The API key to verify
        
    Returns:
        user_id if the API key is valid, None otherwise
    """
    # Check Redis cache first
    cache_key = f"apikey:{api_key}"
    cached_user_id = redis_client.get(cache_key)
    
    if cached_user_id:
        # Update last used timestamp in database (async)
        # This would be better with a background task
        return cached_user_id
    
    # Not in cache, check database
    db = SessionLocal()
    try:
        db_api_key = db.query(ApiKey).filter(
            ApiKey.key == api_key,
            ApiKey.is_active == True
        ).first()
        
        if not db_api_key:
            return None
        
        # Update last used timestamp
        from datetime import datetime
        db_api_key.last_used_at = datetime.utcnow()
        db.commit()
        
        # Cache the result
        redis_client.set(cache_key, db_api_key.user_id, ex=API_KEY_CACHE_TTL)
        
        return db_api_key.user_id
    finally:
        db.close()