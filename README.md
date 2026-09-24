<img src="docs/logo.svg" alt="SentryFlow" width="72" />

# SentryFlow

**Real-time API rate limiting and usage analytics.**

SentryFlow is an API gateway that authenticates callers, enforces per-user
rate limits, and streams every request into an analytics pipeline. A React
dashboard shows live usage, latency and throttling from that pipeline, and
lets administrators change limits that apply on the next request.

---

## Architecture

```
 client ──x-api-key──┐
                     ▼
               ┌─────────────┐  authenticate   API key, cached in Redis
               │   Gateway   │  rate limit     Redis + Lua, atomic
 dashboard ───▶│  (FastAPI)  │  record         Kafka, fire-and-forget
 (React, JWT)  └──┬───────▲──┘  analytics      read-only ClickHouse queries
                  │       │
                  ▼       │
             ┌───────┐  ┌─┴──────────┐
             │ Kafka │  │ ClickHouse │
             └───┬───┘  └─▲──────────┘
                 │        │
                 └──▶ Aggregator  (batches of 1,000 or every 2 s)
```

Each request passes through one middleware chain in a fixed order:
**authenticate → rate limit → serve → record**. Authentication precedes rate
limiting so an unauthenticated caller cannot burn another user's budget.

| Layer | Technology |
| --- | --- |
| Gateway | Python 3.11, FastAPI, SQLAlchemy |
| Rate limiting | Redis with Lua scripts |
| Identity | JWT (dashboard), API keys (machine callers) |
| Streaming | Kafka (`aiokafka`) |
| Analytics | ClickHouse; percentiles computed at query time from raw events |
| Dashboard | React 18, Chart.js, Tailwind; refreshes every 10 s |
| Orchestration | Kubernetes (Helm), Docker Compose for local |
| Cloud | AWS — EKS, RDS, ElastiCache, MSK, ECR, ALB |

---

## Rate limiting

Two algorithms, both implemented as Redis Lua scripts so the
read-modify-write cycle is atomic on the server. Doing this in Python would
need a `WATCH`/`MULTI` retry loop and would still lose under contention.

**Sliding window** — one sorted-set entry per request, scored by timestamp,
trimmed to the trailing window. Precise at the boundary: a fixed window lets a
caller send twice the limit across the boundary instant, a sliding window does
not. Costs O(log N) and one member per in-flight request.

**Token bucket** — two fields per key regardless of traffic, refilled lazily
from elapsed time. Allows a deliberate burst above the steady rate.

Limits resolve per user and per endpoint (exact match, then a `*` wildcard,
then global defaults), cached in Redis for 60s so the database stays off the
hot path. Misses are cached too, so callers on defaults never re-query.

Both scripts are deterministic — timestamps and sorted-set members are passed
in as arguments rather than generated inside Lua — so they replicate safely.

Responses carry `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and on a 429 a
`Retry-After` computed from when the oldest request ages out.

---

## Quick start

```bash
SENTRYFLOW_ADMIN_PASSWORD=choose-one docker compose up -d --build
```

A one-shot `migrate` service creates the schema and the `admin` account. Leave
`SENTRYFLOW_ADMIN_PASSWORD` unset and it generates one instead
(`docker compose logs migrate`). Sign in to the dashboard as `admin` to see
every user's traffic and edit limits; accounts created through sign-up see
only their own.

| | |
| --- | --- |
| Dashboard | http://localhost |
| API docs | http://localhost:8000/docs |
| Kafka UI | http://localhost:8080 (`docker compose --profile tools up -d kafka-ui`) |

Host ports move with `BACKEND_PORT`, `DASHBOARD_PORT` and friends if something
else already holds them.

Without Docker (SQLite, and no analytics without Kafka and ClickHouse):

```bash
pip install -r backend/requirements.txt
python -m backend.setup_db
uvicorn backend.main:app --reload

cd frontend && npm install && npm start
```

### Using the gateway

```bash
# 1. Register and log in (form-encoded: OAuth2 password flow)
curl -X POST localhost:8000/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","email":"demo@example.com","password":"demo-password"}'

TOKEN=$(curl -s -X POST localhost:8000/auth/login \
  -d 'username=demo&password=demo-password' | python -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

# 2. Mint an API key
KEY=$(curl -s -X POST localhost:8000/auth/apikeys/create \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"demo-key"}' | python -c 'import json,sys;print(json.load(sys.stdin)["key"])')

# 3. Call through the gateway
curl -i localhost:8000/api/v1/hello -H "x-api-key: $KEY"
```

---

## Tests

```bash
cd backend && pytest          # gateway, auth, limiter, analytics API
cd aggregator && pytest       # Kafka -> ClickHouse ingestion
cd frontend && npm test       # dashboard helpers and pages
```

| Suite | Tests | Coverage |
| --- | ---: | ---: |
| Backend | 250 | **94%** statement and branch (CI floor 90%) |
| Aggregator | 32 | 99% (CI floor 90%) |
| Analytics SQL, against real ClickHouse | 11 | — |
| Frontend | 97 | — |

The unit suites need no running services. Postgres is replaced by SQLite;
Redis by `fakeredis`, which runs the real Lua scripts, so the limiter
algorithms are genuinely under test; Kafka by a recording double; and
ClickHouse by canned rows per named query. Because canned rows cannot prove
SQL correct, `backend/tests/integration` runs every analytics query against a
real ClickHouse (a service container in CI) with known events and checks the
numbers.

Coverage of the gateway middleware is understated by a couple of points: the
tracer stops following a coroutine at its first `await`, so lines after it
read as uncovered even though `tests/test_gateway.py` drives them over HTTP.

Beyond happy paths, the suites cover: sliding-window boundary behaviour,
token-bucket refill and capping, fail-open and fail-closed on a Redis outage,
refresh tokens rejected as access tokens, forged and expired tokens, per-user
data scoping and admin-only writes, limit changes applying on the very next
request, revocation evicting the cache, Kafka outages not reaching callers,
and at-least-once commit ordering in the aggregator.

---

## Deployment

Helm chart in [`kubernetes/chart`](kubernetes/chart), full guide in
[`docs/deployment.md`](docs/deployment.md).

```bash
helm upgrade --install sentryflow ./kubernetes/chart \
  --namespace sentryflow --create-namespace \
  -f ./kubernetes/chart/values-production.yaml \
  --set image.tag=$(git rev-parse --short HEAD) --wait
```

Rendered manifests are validated against real Kubernetes schemas in CI
(`kubeconform -strict`).

---

## Design decisions

**Liveness checks nothing.** `/health/live` touches no dependency; a liveness
probe that checked Redis would restart every pod during a Redis blip, turning
a degraded dependency into an outage. `/health/ready` checks Postgres and
Redis, so an affected pod leaves the Service and rejoins on recovery without a
restart.

**Kafka is non-critical.** Usage logging is fire-and-forget — the producer
buffers and the request returns without waiting for a broker ack, because
waiting would put Kafka round-trip latency on every client request. A broker
outage loses analytics events rather than failing requests. That is the right
trade for usage data and the wrong one for billing.

**The limiter fails open.** If Redis is unreachable, requests are served
without enforcement (`RATE_LIMIT_FAIL_OPEN`, default true). Losing the rate
limiter should degrade enforcement, not cause an API outage. Authentication,
by contrast, never fails open — a cache outage degrades it to
database-per-request.

**No secrets in source.** The JWT signing key is read from the environment,
and the application refuses to boot when `ENVIRONMENT=production` and
`JWT_SECRET` is unset rather than falling back to a default. In development it
mints an ephemeral key.

**Revocation evicts the cache.** API keys are cached for an hour, so
deactivating the row alone would leave a revoked key working until the TTL
lapsed. Changing or deleting a rate-limit rule does the same for the cached
rule resolution, so new limits apply on the next request.

**Operators set limits, customers do not.** Anyone can read the limits that
apply to them, but only admins can change them; a customer who could raise
their own limit would not really have one. Users see only their own traffic,
and asking for someone else's is a 403, not an empty result.

**Analytics are computed at query time.** The aggregator writes raw events and
ClickHouse aggregates on read. Percentiles cannot be rebuilt from
pre-aggregated percentiles, and there are no rollup tables to keep consistent.
The dashboard's ClickHouse connection is read-only and time-bounded.

---

## Documentation

- [API reference](docs/api.md)
- [Rate limiting](docs/rate-limiting.md)
- [Analytics pipeline](docs/analytics.md)
- [Deployment](docs/deployment.md)

## Licence

MIT — see [LICENSE](LICENSE).
