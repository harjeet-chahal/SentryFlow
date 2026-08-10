import os
import time
from clickhouse_driver import Client
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_fixed

# Load environment variables
load_dotenv()

# ClickHouse connection parameters
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", 9000))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "sentryflow")


@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def get_clickhouse_client():
    """Create and return a ClickHouse client with retry logic."""
    return Client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
    )


def create_database():
    """Create the ClickHouse database if it doesn't exist."""
    client = get_clickhouse_client()
    client.execute(f"CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DATABASE}")
    print(f"Database '{CLICKHOUSE_DATABASE}' created or already exists.")


def create_api_requests_table():
    """Create the api_requests table for storing API request data."""
    client = get_clickhouse_client()
    client.execute(f"USE {CLICKHOUSE_DATABASE}")
    
    # Create the api_requests table
    client.execute("""
    CREATE TABLE IF NOT EXISTS api_requests (
        request_id String,
        timestamp DateTime,
        user_id String,
        api_key_id String,
        endpoint String,
        method String,
        status_code UInt16,
        response_time_ms Float64,
        ip_address String,
        user_agent String,
        request_size UInt32,
        response_size UInt32,
        error_message String DEFAULT '',
        date Date DEFAULT toDate(timestamp)
    ) ENGINE = MergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (timestamp, user_id, endpoint)
    TTL date + INTERVAL 90 DAY
    SETTINGS index_granularity = 8192
    """)
    print("api_requests table created or already exists.")


def create_rate_limited_table():
    """Create the rate_limited_events table for storing rate limiting events."""
    client = get_clickhouse_client()
    client.execute(f"USE {CLICKHOUSE_DATABASE}")
    
    # Create the rate_limited_events table
    client.execute("""
    CREATE TABLE IF NOT EXISTS rate_limited_events (
        event_id String,
        timestamp DateTime,
        user_id String,
        api_key_id String,
        endpoint String,
        method String,
        ip_address String,
        limit_type String,
        limit_value UInt32,
        window_seconds UInt32,
        current_usage UInt32,
        date Date DEFAULT toDate(timestamp)
    ) ENGINE = MergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (timestamp, user_id, endpoint)
    TTL date + INTERVAL 90 DAY
    SETTINGS index_granularity = 8192
    """)
    print("rate_limited_events table created or already exists.")


def create_aggregated_metrics_table():
    """Create the aggregated_metrics table for storing pre-aggregated metrics."""
    client = get_clickhouse_client()
    client.execute(f"USE {CLICKHOUSE_DATABASE}")
    
    # Create the aggregated_metrics table
    client.execute("""
    CREATE TABLE IF NOT EXISTS aggregated_metrics (
        metric_id String,
        timestamp DateTime,
        metric_type String,
        user_id String DEFAULT '',
        api_key_id String DEFAULT '',
        endpoint String DEFAULT '',
        status_code UInt16 DEFAULT 0,
        time_bucket String,
        count UInt64,
        sum_response_time Float64 DEFAULT 0,
        avg_response_time Float64 DEFAULT 0,
        min_response_time Float64 DEFAULT 0,
        max_response_time Float64 DEFAULT 0,
        p95_response_time Float64 DEFAULT 0,
        p99_response_time Float64 DEFAULT 0,
        date Date DEFAULT toDate(timestamp)
    ) ENGINE = MergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (timestamp, metric_type, time_bucket, user_id, endpoint)
    TTL date + INTERVAL 365 DAY
    SETTINGS index_granularity = 8192
    """)
    print("aggregated_metrics table created or already exists.")


def create_materialized_views():
    """Create materialized views for real-time aggregations."""
    client = get_clickhouse_client()
    client.execute(f"USE {CLICKHOUSE_DATABASE}")
    
    # Create hourly requests by endpoint materialized view
    client.execute("""
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_requests_by_endpoint
    ENGINE = SummingMergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (timestamp, endpoint, status_code)
    POPULATE AS
    SELECT
        toStartOfHour(timestamp) AS timestamp,
        endpoint,
        status_code,
        count() AS request_count,
        avg(response_time_ms) AS avg_response_time,
        sum(response_time_ms) AS total_response_time,
        min(response_time_ms) AS min_response_time,
        max(response_time_ms) AS max_response_time
    FROM api_requests
    GROUP BY timestamp, endpoint, status_code
    """)
    print("mv_hourly_requests_by_endpoint materialized view created or already exists.")
    
    # Create hourly requests by user materialized view
    client.execute("""
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_requests_by_user
    ENGINE = SummingMergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (timestamp, user_id, status_code)
    POPULATE AS
    SELECT
        toStartOfHour(timestamp) AS timestamp,
        user_id,
        status_code,
        count() AS request_count,
        avg(response_time_ms) AS avg_response_time,
        sum(response_time_ms) AS total_response_time,
        min(response_time_ms) AS min_response_time,
        max(response_time_ms) AS max_response_time
    FROM api_requests
    GROUP BY timestamp, user_id, status_code
    """)
    print("mv_hourly_requests_by_user materialized view created or already exists.")
    
    # Create hourly rate limited events materialized view
    client.execute("""
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_rate_limited
    ENGINE = SummingMergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (timestamp, endpoint, user_id)
    POPULATE AS
    SELECT
        toStartOfHour(timestamp) AS timestamp,
        endpoint,
        user_id,
        count() AS rate_limited_count
    FROM rate_limited_events
    GROUP BY timestamp, endpoint, user_id
    """)
    print("mv_hourly_rate_limited materialized view created or already exists.")


def main():
    """Main function to set up ClickHouse database and tables."""
    try:
        print("Setting up ClickHouse database and tables...")
        create_database()
        time.sleep(1)  # Small delay to ensure database is ready
        create_api_requests_table()
        create_rate_limited_table()
        create_aggregated_metrics_table()
        create_materialized_views()
        print("ClickHouse setup completed successfully!")
    except Exception as e:
        print(f"Error setting up ClickHouse: {e}")


if __name__ == "__main__":
    main()