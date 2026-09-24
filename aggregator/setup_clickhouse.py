"""ClickHouse schema for gateway usage events.

The aggregator owns this schema and ensures it on startup. Running this
module directly does the same, for operators who prefer an explicit step:

    python -m aggregator.setup_clickhouse

One table holds every request event the gateway publishes. The dashboard's
analytics are computed from it at query time (backend/analytics/queries.py),
so there are no rollup tables to keep consistent.
"""
import logging
import os
import re

from clickhouse_driver import Client
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
DATABASE = os.getenv("CLICKHOUSE_DATABASE", "sentryflow")
RETENTION_DAYS = int(os.getenv("USAGE_RETENTION_DAYS", "90"))

# Partitioned by day so retention drops whole parts instead of rewriting
# them. Ordered by user first because most dashboard reads are one user's.
API_USAGE_DDL = """
CREATE TABLE IF NOT EXISTS {database}.api_usage
(
    timestamp     DateTime,
    user_id       String,
    endpoint      String,
    status_code   UInt16,
    response_time UInt32
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (user_id, endpoint, timestamp)
TTL timestamp + INTERVAL {retention_days} DAY
"""

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _checked_identifier(name: str) -> str:
    """The database name is interpolated into DDL, so it must be a bare identifier."""
    if not _IDENTIFIER.match(name):
        raise ValueError(f"Invalid ClickHouse database name: {name!r}")
    return name


def connect() -> Client:
    """A client with no default database, which may not exist yet."""
    return Client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        connect_timeout=5,
    )


def ensure_schema(client: Client, database: str = DATABASE, retention_days: int = RETENTION_DAYS) -> None:
    """Create the database and events table if missing. Safe to re-run."""
    database = _checked_identifier(database)
    client.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
    client.execute(API_USAGE_DDL.format(database=database, retention_days=int(retention_days)))
    logger.info("ClickHouse schema ready in %s", database)


@retry(stop=stop_after_attempt(30), wait=wait_fixed(2), reraise=True)
def ensure_schema_when_ready(client: Client) -> None:
    """ensure_schema, retried while ClickHouse is still starting up."""
    ensure_schema(client)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    logging.basicConfig(level=logging.INFO)
    client = connect()
    try:
        ensure_schema_when_ready(client)
    finally:
        client.disconnect()


if __name__ == "__main__":  # pragma: no cover
    main()
