import json
import os
import asyncio
from aiokafka import AIOKafkaConsumer
from datetime import datetime, timedelta
from typing import Dict, List, Any
import clickhouse_driver

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
API_REQUESTS_TOPIC = "api-requests"
RATE_LIMITED_TOPIC = "rate-limited-events"

# ClickHouse configuration
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "sentryflow")

# Batch size for processing messages
BATCH_SIZE = 1000

# Aggregation intervals in minutes
AGGREGATION_INTERVALS = [1, 5, 60]  # 1 minute, 5 minutes, 1 hour


class ClickHouseClient:
    """Client for interacting with ClickHouse database."""
    
    def __init__(self):
        self.client = clickhouse_driver.Client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            user=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DATABASE
        )
    
    def create_tables(self):
        """Create necessary tables if they don't exist."""
        # Raw events table
        self.client.execute("""
        CREATE TABLE IF NOT EXISTS api_usage (
            timestamp DateTime,
            user_id String,
            endpoint String,
            status_code UInt16,
            response_time UInt32
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMMDD(timestamp)
        ORDER BY (user_id, endpoint, timestamp)
        """)
        
        # Aggregated metrics table
        self.client.execute("""
        CREATE TABLE IF NOT EXISTS api_usage_aggregated (
            timestamp DateTime,
            user_id String,
            endpoint String,
            interval_minutes UInt8,
            request_count UInt32,
            error_count UInt32,
            rate_limited_count UInt32,
            avg_response_time Float32,
            p95_response_time Float32,
            p99_response_time Float32
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMMDD(timestamp)
        ORDER BY (interval_minutes, user_id, endpoint, timestamp)
        """)
    
    def insert_raw_events(self, events: List[Dict[str, Any]]):
        """Insert raw events into the api_usage table.
        
        Args:
            events: List of event dictionaries
        """
        if not events:
            return
        
        # Prepare data for insertion
        data = [(
            datetime.fromisoformat(event["timestamp"].replace('Z', '+00:00')),
            event["user_id"],
            event["endpoint"],
            event["status_code"],
            event["response_time"]
        ) for event in events]
        
        # Insert into ClickHouse
        self.client.execute(
            "INSERT INTO api_usage (timestamp, user_id, endpoint, status_code, response_time) VALUES",
            data
        )
    
    def aggregate_metrics(self, interval_minutes: int):
        """Aggregate metrics for a specific time interval.
        
        Args:
            interval_minutes: The aggregation interval in minutes
        """
        # Calculate the start time for aggregation (previous complete interval)
        now = datetime.utcnow()
        interval_seconds = interval_minutes * 60
        start_time = now - timedelta(seconds=now.timestamp() % interval_seconds + interval_seconds)
        end_time = start_time + timedelta(minutes=interval_minutes)
        
        # Execute aggregation query
        self.client.execute("""
        INSERT INTO api_usage_aggregated
        SELECT
            toStartOfInterval(timestamp, INTERVAL {interval} MINUTE) AS timestamp,
            user_id,
            endpoint,
            {interval_minutes} AS interval_minutes,
            count() AS request_count,
            countIf(status_code >= 400) AS error_count,
            countIf(status_code = 429) AS rate_limited_count,
            avg(response_time) AS avg_response_time,
            quantile(0.95)(response_time) AS p95_response_time,
            quantile(0.99)(response_time) AS p99_response_time
        FROM api_usage
        WHERE timestamp >= '{start_time}' AND timestamp < '{end_time}'
        GROUP BY timestamp, user_id, endpoint
        """.format(
            interval=interval_minutes,
            interval_minutes=interval_minutes,
            start_time=start_time.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=end_time.strftime("%Y-%m-%d %H:%M:%S")
        ))


async def consume_messages():
    """Consume messages from Kafka and process them."""
    # Initialize ClickHouse client
    clickhouse = ClickHouseClient()
    clickhouse.create_tables()
    
    # Create Kafka consumer
    consumer = AIOKafkaConsumer(
        API_REQUESTS_TOPIC,
        RATE_LIMITED_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id="analytics-aggregator",
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
        auto_offset_reset="earliest"
    )
    
    # Start consumer
    await consumer.start()
    
    try:
        # Process messages in batches
        batch = []
        async for msg in consumer:
            # Add message to batch
            batch.append(msg.value)
            
            # Process batch when it reaches the batch size
            if len(batch) >= BATCH_SIZE:
                clickhouse.insert_raw_events(batch)
                batch = []
    finally:
        # Close consumer
        await consumer.stop()


async def run_aggregation_tasks():
    """Run periodic aggregation tasks."""
    clickhouse = ClickHouseClient()
    
    while True:
        # Run aggregations for each interval
        for interval in AGGREGATION_INTERVALS:
            try:
                clickhouse.aggregate_metrics(interval)
            except Exception as e:
                print(f"Error aggregating metrics for {interval} minute interval: {str(e)}")
        
        # Wait for next aggregation cycle (run every minute)
        await asyncio.sleep(60)


async def main():
    """Main function to run the consumer and aggregation tasks."""
    # Create tasks
    consumer_task = asyncio.create_task(consume_messages())
    aggregation_task = asyncio.create_task(run_aggregation_tasks())
    
    # Wait for tasks to complete
    await asyncio.gather(consumer_task, aggregation_task)


if __name__ == "__main__":
    # Run the main function
    asyncio.run(main())