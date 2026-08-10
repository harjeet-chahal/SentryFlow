import json
import os
from aiokafka import AIOKafkaProducer
from typing import Dict, Any

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# Global producer instance
_producer = None


async def get_kafka_producer():
    """Get or create the Kafka producer."""
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        await _producer.start()
    return _producer


async def send_message(topic: str, message: Dict[str, Any]):
    """Send a message to a Kafka topic.
    
    Args:
        topic: The Kafka topic to send to
        message: The message payload as a dictionary
    """
    producer = await get_kafka_producer()
    await producer.send_and_wait(topic, message)


async def shutdown():
    """Shutdown the Kafka producer."""
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None