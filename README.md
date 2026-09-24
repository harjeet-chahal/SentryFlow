<img src="docs/logo.svg" alt="SentryFlow" width="72" />

# SentryFlow

**Real-time API rate limiting and usage analytics.**

SentryFlow is an API gateway that authenticates callers, enforces per-user
rate limits, and streams every request into an analytics pipeline. It ships
with a React dashboard for usage, latency and throttling metrics.

---

## Architecture

```
          ┌──────────────┐
  client ─┤   Gateway    ├─ authenticate (API key, Redis-cached)
          │  (FastAPI)   ├─ rate limit   (Redis + Lua, atomic)
          └──────┬───────┘─ log usage    (Kafka, fire-and-forget)
                 │
                 ▼
          ┌──────────────┐        ┌──────────────┐
          │    Kafka     │───────▶│  Aggregator  │
          └──────────────┘        └──────┬───────┘
                                         ▼
                                  ┌──────────────┐     ┌───────────┐
                                  │  ClickHouse  │◀────│ Dashboard │
                                  └──────────────┘     │  (React)  │
                                                       └───────────┘
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
| Analytics | ClickHouse, MergeTree with p95/p99 rollups |
| Dashboard | React 18, Chart.js, Tailwind |
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
docker compose up -d
docker compose exec backend python -m backend.setup_db
```

| | |
| --- | --- |
| Dashboard | http://localhost |
| API docs | http://localhost:8000/docs |
| Kafka UI | http://localhost:8080 |

Without Docker:

```bash
pip install -r backend/requirements.txt
python -m backend.setup_db                      # SQLite by default
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
cd backend && pytest
```

143 tests, **92% statement and branch coverage**, enforced in CI at a 90%
floor. The suite needs no running services: Postgres is replaced by SQLite,
Redis by `fakeredis` — which executes the real Lua scripts rather than
stubbing them, so the limiter algorithms are genuinely under test — and Kafka
by a recording double.

Coverage of the gateway middleware is understated by roughly two points: the
tracer stops following a coroutine at its first `await`, so lines in
`gateway_middleware` after the first suspension read as uncovered even though
`tests/test_gateway.py` drives them over real HTTP.

What the suite covers beyond happy paths: boundary behaviour that distinguishes
sliding window from fixed window, token-bucket refill and capping, config
resolution and negative caching, fail-open and fail-closed on a Redis outage,
refresh-token-as-access-token rejection, forged and expired tokens, cross-user
key isolation, revocation evicting the cache, and Kafka outages not surfacing
to callers.

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
lapsed.

---

## Documentation

- [API reference](docs/api.md)
- [Rate limiting](docs/rate-limiting.md)
- [Analytics pipeline](docs/analytics.md)
- [Deployment](docs/deployment.md)

## Licence

MIT — see [LICENSE](LICENSE).
