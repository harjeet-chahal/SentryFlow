#!/usr/bin/env python3
"""
Generate mock data for SentryFlow development and testing.

This script generates mock API request data and rate limited events,
and sends them to Kafka topics for processing by the aggregator.
"""

import os
import json
import random
import uuid
import asyncio
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Any

from aiokafka import AIOKafkaProducer
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
API_REQUESTS_TOPIC = os.getenv("KAFKA_API_REQUESTS_TOPIC", "api-requests")
RATE_LIMITED_TOPIC = os.getenv("KAFKA_RATE_LIMITED_TOPIC", "rate-limited-events")

# Mock data configuration
USER_IDS = [f"user_{i}" for i in range(1, 11)]
API_KEY_IDS = [f"api_key_{i}" for i in range(1, 21)]
ENDPOINTS = [
    "/api/v1/users",
    "/api/v1/users/{id}",
    "/api/v1/products",
    "/api/v1/products/{id}",
    "/api/v1/orders",
    "/api/v1/orders/{id}",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/refresh",
    "/api/v1/search",
]
METHODS = ["GET", "POST", "PUT", "DELETE"]
STATUS_CODES = [
    200, 200, 200, 200, 200,  # 50% 200 OK
    201, 201,                # 20% 201 Created
    400, 401, 403, 404,      # 40% 4xx Client Errors
    500,                     # 10% 500 Server Error
]
IP_ADDRESSES = [
    "192.168.1.1",
    "10.0.0.1",
    "172.16.0.1",
    "127.0.0.1",
    "8.8.8.8",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
    "PostmanRuntime/7.28.0",
    "curl/7.64.1",
    "python-requests/2.26.0",
]


def generate_api_request(timestamp: datetime = None) -> Dict[str, Any]:
    """Generate a mock API request event.
    
    Args:
        timestamp: Optional timestamp for the event. If not provided, a random
            timestamp within the last 24 hours will be used.
    
    Returns:
        Dict containing the mock API request data.
    """
    # Generate timestamp if not provided
    if timestamp is None:
        # Random timestamp within the last 24 hours
        timestamp = datetime.utcnow() - timedelta(seconds=random.randint(0, 86400))
    
    # Generate status code with weighted distribution
    status_code = random.choice(STATUS_CODES)
    
    # Generate response time based on status code
    if status_code >= 500:
        # Server errors tend to have higher response times
        response_time_ms = random.uniform(500, 2000)
    elif status_code >= 400:
        # Client errors have moderate response times
        response_time_ms = random.uniform(100, 500)
    else:
        # Successful responses have lower response times
        response_time_ms = random.uniform(10, 200)
    
    # Generate request and response sizes
    request_size = random.randint(100, 10000)
    response_size = random.randint(100, 100000)
    
    # Generate error message for error status codes
    error_message = ""
    if status_code >= 400:
        error_messages = {
            400: "Bad Request: Invalid parameters",
            401: "Unauthorized: Authentication required",
            403: "Forbidden: Insufficient permissions",
            404: "Not Found: Resource does not exist",
            500: "Internal Server Error",
        }
        error_message = error_messages.get(status_code, "Unknown error")
    
    return {
        "request_id": str(uuid.uuid4()),
        "timestamp": timestamp.isoformat() + "Z",
        "user_id": random.choice(USER_IDS),
        "api_key_id": random.choice(API_KEY_IDS),
        "endpoint": random.choice(ENDPOINTS),
        "method": random.choice(METHODS),
        "status_code": status_code,
        "response_time_ms": round(response_time_ms, 2),
        "ip_address": random.choice(IP_ADDRESSES),
        "user_agent": random.choice(USER_AGENTS),
        "request_size": request_size,
        "response_size": response_size,
        "error_message": error_message,
    }


def generate_rate_limited_event(timestamp: datetime = None) -> Dict[str, Any]:
    """Generate a mock rate limited event.
    
    Args:
        timestamp: Optional timestamp for the event. If not provided, a random
            timestamp within the last 24 hours will be used.
    
    Returns:
        Dict containing the mock rate limited event data.
    """
    # Generate timestamp if not provided
    if timestamp is None:
        # Random timestamp within the last 24 hours
        timestamp = datetime.utcnow() - timedelta(seconds=random.randint(0, 86400))
    
    # Generate limit type
    limit_types = ["global", "user", "ip", "endpoint"]
    limit_type = random.choice(limit_types)
    
    # Generate limit value and window based on limit type
    if limit_type == "global":
        limit_value = random.choice([1000, 5000, 10000])
        window_seconds = random.choice([60, 300, 3600])
    elif limit_type == "user":
        limit_value = random.choice([100, 500, 1000])
        window_seconds = random.choice([60, 300, 3600])
    elif limit_type == "ip":
        limit_value = random.choice([50, 200, 500])
        window_seconds = random.choice([60, 300, 3600])
    else:  # endpoint
        limit_value = random.choice([20, 50, 100])
        window_seconds = random.choice([60, 300, 3600])
    
    # Generate current usage (always at or above the limit)
    current_usage = limit_value + random.randint(0, 100)
    
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": timestamp.isoformat() + "Z",
        "user_id": random.choice(USER_IDS),
        "api_key_id": random.choice(API_KEY_IDS),
        "endpoint": random.choice(ENDPOINTS),
        "method": random.choice(METHODS),
        "ip_address": random.choice(IP_ADDRESSES),
        "limit_type": limit_type,
        "limit_value": limit_value,
        "window_seconds": window_seconds,
        "current_usage": current_usage,
    }


async def send_to_kafka(producer: AIOKafkaProducer, topic: str, data: Dict[str, Any]):
    """Send data to Kafka topic.
    
    Args:
        producer: Kafka producer instance
        topic: Kafka topic to send data to
        data: Data to send
    """
    try:
        # Convert data to JSON and encode as bytes
        value = json.dumps(data).encode()
        # Send data to Kafka
        await producer.send_and_wait(topic, value)
    except Exception as e:
        print(f"Error sending data to Kafka: {str(e)}")


async def generate_and_send_data(num_requests: int, num_rate_limited: int, time_range_hours: int):
    """Generate and send mock data to Kafka.
    
    Args:
        num_requests: Number of API request events to generate
        num_rate_limited: Number of rate limited events to generate
        time_range_hours: Time range in hours for the generated data
    """
    # Create Kafka producer
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        acks="all",
    )
    
    # Start producer
    await producer.start()
    
    try:
        print(f"Generating {num_requests} API request events...")
        
        # Generate and send API request events
        for i in range(num_requests):
            # Generate timestamp within the specified time range
            timestamp = datetime.utcnow() - timedelta(
                seconds=random.randint(0, time_range_hours * 3600)
            )
            
            # Generate API request event
            request = generate_api_request(timestamp)
            
            # Send to Kafka
            await send_to_kafka(producer, API_REQUESTS_TOPIC, request)
            
            # Print progress
            if (i + 1) % 100 == 0 or i + 1 == num_requests:
                print(f"Sent {i + 1}/{num_requests} API request events")
        
        print(f"Generating {num_rate_limited} rate limited events...")
        
        # Generate and send rate limited events
        for i in range(num_rate_limited):
            # Generate timestamp within the specified time range
            timestamp = datetime.utcnow() - timedelta(
                seconds=random.randint(0, time_range_hours * 3600)
            )
            
            # Generate rate limited event
            event = generate_rate_limited_event(timestamp)
            
            # Send to Kafka
            await send_to_kafka(producer, RATE_LIMITED_TOPIC, event)
            
            # Print progress
            if (i + 1) % 100 == 0 or i + 1 == num_rate_limited:
                print(f"Sent {i + 1}/{num_rate_limited} rate limited events")
        
        print("Done!")
    finally:
        # Stop producer
        await producer.stop()


def main():
    """Main function to parse arguments and run the script."""
    parser = argparse.ArgumentParser(description="Generate mock data for SentryFlow")
    parser.add_argument(
        "--requests", type=int, default=1000,
        help="Number of API request events to generate (default: 1000)"
    )
    parser.add_argument(
        "--rate-limited", type=int, default=100,
        help="Number of rate limited events to generate (default: 100)"
    )
    parser.add_argument(
        "--time-range", type=int, default=24,
        help="Time range in hours for the generated data (default: 24)"
    )
    
    args = parser.parse_args()
    
    # Run the async function
    asyncio.run(generate_and_send_data(
        args.requests, args.rate_limited, args.time_range
    ))


if __name__ == "__main__":
    main()