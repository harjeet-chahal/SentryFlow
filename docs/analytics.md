# Analytics pipeline

Every request through the gateway becomes one row in ClickHouse, and the
dashboard computes everything from those rows at query time.

```
 client ──► gateway ──► Kafka ──► aggregator ──► ClickHouse ◄── /analytics/* ◄── dashboard
            (FastAPI)   api-requests              api_usage        (FastAPI)       (React,
                        rate-limited-events                                          polls 10 s)
```

## 1. The gateway emits an event

After a request is served, or rejected with 429, the gateway hands one event
to its Kafka producer:

```json
{ "timestamp": "2026-09-24T12:00:05.123456+00:00", "user_id": "…",
  "endpoint": "/api/v1/hello", "status_code": 200, "response_time": 2 }
```

- `response_time` is milliseconds the gateway spent on the request: key
  lookup, limit check and handler, rounded.
- 429s go to `rate-limited-events`, everything else to `api-requests`. Events
  are keyed by user, so one user's events stay ordered within a partition.
- Sending is **fire-and-forget**: the event goes into the producer's buffer
  and the request returns without waiting for a broker acknowledgement. A
  Kafka outage loses events rather than failing requests, which is the right
  trade for usage analytics (and would be the wrong one for billing).
- Requests rejected with 401 are not recorded; there is no user to attribute
  them to.

## 2. The aggregator writes batches

`aggregator/batch_consumer.py` consumes both topics as the
`analytics-aggregator` consumer group and inserts into ClickHouse.

- **Batching.** A batch is written when it holds 1,000 events *or* its oldest
  event has waited 2 seconds, whichever comes first (`BATCH_SIZE`,
  `FLUSH_INTERVAL_SECONDS`). The time bound is what makes the dashboard
  live; without it a quiet system would sit on events until the thousandth.
- **At-least-once.** Offsets are committed only after the batch is written. A
  crash between the two replays the batch instead of losing it; the cost is
  possible duplicate rows.
- **Failures.** A failed insert is retried with backoff (1, 2, 4, 8 s). After
  five failures the process exits without committing, and on restart it
  re-reads the batch from Kafka. Kafka is the buffer, not memory.
- **Bad events** are logged and skipped, and their offsets still committed, so
  one malformed message cannot wedge the consumer.
- **Startup** waits for ClickHouse and Kafka, creates the table and the topics
  if they are missing, and then subscribes. Creating the topics first matters:
  a consumer that subscribes before a topic exists only notices it on a
  metadata refresh minutes later.
- **Shutdown** on SIGTERM flushes the current batch and commits.

## 3. One ClickHouse table

`aggregator/setup_clickhouse.py` owns the schema:

```sql
CREATE TABLE sentryflow.api_usage
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
TTL timestamp + INTERVAL 90 DAY
```

- Sorted by user first, because most dashboard reads are one user's traffic.
- Daily partitions, so retention (`USAGE_RETENTION_DAYS`, default 90) drops
  whole parts instead of rewriting them.
- Timestamps are written as Unix seconds, which leaves no room for a
  timezone mix-up between the aggregator and the server.

There are no rollup tables. Latency percentiles have to come from raw rows
(a p95 cannot be averaged from per-minute p95s), and ClickHouse scans raw rows
quickly at this scale. The next step at higher volume would be a materialized
view holding `quantileState` per user, endpoint and minute.

## 4. The analytics API

`backend/analytics/` answers the dashboard. The full contract is in
[api.md](api.md#analytics); the parts that matter for correctness:

- **Scoping.** Users see their own traffic; admins see everyone's or one
  user's. The filter is applied in SQL, not after the fact.
- **Definitions.** *Errors* are 4xx/5xx excluding 429, and throttling is
  reported separately. *Latency* covers served requests only, since 429s are
  cheap and would flatter every percentile.
- **Buckets.** Epoch-aligned (UTC minutes, hours, days) and zero-filled, so a
  chart always has one point per bucket and an empty bucket shows no latency
  rather than zero.
- **Safety.** Every value is a query parameter. The connection runs with
  ClickHouse's `readonly=2` and a `max_execution_time`, so even a bad query
  cannot write or run away. ClickHouse being down returns 503 from the
  analytics API; the gateway keeps serving.
- **Connections.** clickhouse-driver is synchronous and not thread-safe.
  Queries run in the threadpool, one connection per worker thread, and the
  four queries behind one dashboard view run concurrently.

## 5. The dashboard

| Page | Endpoint | Shows |
| --- | --- | --- |
| Dashboard | `/analytics/usage` | requests, error rate, throttling, p95/p99 latency; requests and latency over time; status mix; busiest endpoints |
| Rate Limit Monitor | `/analytics/rate-limits`, `/limits` | allowed vs throttled over time; throttling by endpoint and (admins) by user; the rules in force, editable by admins |
| Logs | `/analytics/logs` | recent requests, filtered in ClickHouse by status class, endpoint and (admins) user |
| Users | `/analytics/users` | admins only: every account with its traffic, drilling into one user's charts |
| API Keys | `/auth/apikeys` | create and revoke keys |

The Dashboard and Rate Limit Monitor refresh every 10 seconds. An event is
visible about 2–3 seconds after its request: up to 2 seconds in the
aggregator's batch, plus the insert and the query. The load test measures this
([load-testing.md](load-testing.md)).

## Testing

- `backend/tests/test_analytics.py`: shaping, scoping, validation and failure
  handling, with ClickHouse replaced by canned rows.
- `backend/tests/integration/`: the SQL itself against a real ClickHouse,
  with the aggregator's schema: counts, percentiles, bucket placement,
  filters, the TTL, and that the dashboard connection cannot write. CI runs it
  with a ClickHouse service container.
- `aggregator/tests/`: parsing, size- and time-based flushing, commit-after-
  write ordering, retries, and topic and schema setup.
