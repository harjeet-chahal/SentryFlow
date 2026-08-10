import os
import time
import asyncio
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from aiokafka import AIOKafkaProducer

from database import get_db
from redis_client import get_redis
from kafka_client import get_kafka_producer

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/health", tags=["health"])


@router.get("/", summary="Get system health status")
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    kafka_producer: AIOKafkaProducer = Depends(get_kafka_producer),
) -> Dict[str, Any]:
    """Check the health of all system components.
    
    Returns:
        Dict with health status of each component and overall system health.
    """
    start_time = time.time()
    health_data = {
        "status": "healthy",
        "timestamp": start_time,
        "components": {},
    }
    
    # Check database connection
    try:
        # Execute a simple query
        await db.execute("SELECT 1")
        health_data["components"]["database"] = {
            "status": "healthy",
            "details": "Connection successful"
        }
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        health_data["components"]["database"] = {
            "status": "unhealthy",
            "details": str(e)
        }
        health_data["status"] = "unhealthy"
    
    # Check Redis connection
    try:
        # Ping Redis
        await redis.ping()
        health_data["components"]["redis"] = {
            "status": "healthy",
            "details": "Connection successful"
        }
    except Exception as e:
        logger.error(f"Redis health check failed: {str(e)}")
        health_data["components"]["redis"] = {
            "status": "unhealthy",
            "details": str(e)
        }
        health_data["status"] = "unhealthy"
    
    # Check Kafka connection
    try:
        # Check if Kafka producer is connected
        if kafka_producer.client.ready:
            health_data["components"]["kafka"] = {
                "status": "healthy",
                "details": "Connection successful"
            }
        else:
            health_data["components"]["kafka"] = {
                "status": "unhealthy",
                "details": "Producer not ready"
            }
            health_data["status"] = "unhealthy"
    except Exception as e:
        logger.error(f"Kafka health check failed: {str(e)}")
        health_data["components"]["kafka"] = {
            "status": "unhealthy",
            "details": str(e)
        }
        health_data["status"] = "unhealthy"
    
    # Add response time
    health_data["response_time_ms"] = round((time.time() - start_time) * 1000, 2)
    
    # If overall status is unhealthy, return 503 Service Unavailable
    if health_data["status"] == "unhealthy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_data
        )
    
    return health_data


@router.get("/ready", summary="Check if the service is ready to accept requests")
async def readiness_check() -> Dict[str, Any]:
    """Check if the service is ready to accept requests.
    
    This is a lightweight check that doesn't verify all dependencies.
    It's useful for Kubernetes readiness probes.
    
    Returns:
        Dict with readiness status.
    """
    return {
        "status": "ready",
        "timestamp": time.time()
    }


@router.get("/live", summary="Check if the service is alive")
async def liveness_check() -> Dict[str, Any]:
    """Check if the service is alive.
    
    This is a very lightweight check that doesn't verify any dependencies.
    It's useful for Kubernetes liveness probes.
    
    Returns:
        Dict with liveness status.
    """
    return {
        "status": "alive",
        "timestamp": time.time()
    }