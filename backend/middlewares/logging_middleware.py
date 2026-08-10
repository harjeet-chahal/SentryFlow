import json
import os
from datetime import datetime
from typing import Optional
from aiokafka import AIOKafkaProducer

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
API_REQUESTS_TOPIC = "api-requests"
RATE_LIMITED_TOPIC = "rate-limited-events"

# Create Kafka producer
producer = None


async def get_producer():
    """Get or create the Kafka producer."""
    global producer
    if producer is None:
        producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        await producer.start()
    return producer


async def log_request(user_id: str, endpoint: str, status_code: int, response_time: int):
    """Log an API request to Kafka.
    
    Args:
        user_id: The user ID making the request
        endpoint: The API endpoint being accessed
        status_code: HTTP status code of the response
        response_time: Response time in milliseconds
    """
    try:
        # Prepare message payload
        message = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "endpoint": endpoint,
            "status_code": status_code,
            "response_time": response_time
        }
        
        # Get Kafka producer
        producer = await get_producer()
        
        # Choose topic based on status code
        topic = RATE_LIMITED_TOPIC if status_code == 429 else API_REQUESTS_TOPIC
        
        # Send message to Kafka
        await producer.send_and_wait(topic, message)
    except Exception as e:
        # In production, log this error properly
        print(f"Error sending to Kafka: {str(e)}")


async def shutdown():
    """Shutdown the Kafka producer."""
    if producer is not None:
        await producer.stop()