# Load testing

`loadtest/gateway.js` is a [k6](https://k6.io) script that drives the gateway
and checks three properties at once.

| Scenario | What it does | Pass condition |
| --- | --- | --- |
| **steady** | `RATE` requests/s for `DURATION` through the full gateway path: API-key lookup, the sliding-window Lua script in Redis, the handler, and the Kafka usage event | p95 **and** p99 under 100 ms; under 0.1% failures |
| **throttle** | one caller limited to 30 requests/minute sends 5/s from several VUs for 45 s | exactly 30 succeed; every other response is a 429 with `Retry-After` |
| **freshness** | mid-run, a new user sends 20 requests and polls `/analytics/usage` until they appear | visible in under 10 s |

The thresholds are the pass/fail gate: k6 exits non-zero if any is missed.

## Running it

k6 runs from its container on the compose network, so it measures the gateway
rather than Docker Desktop's port forwarding. Setup signs up two throwaway
users and sets their limits through the admin API, so it needs the admin
password (`docker compose logs migrate` shows a generated one).

```bash
docker compose up -d --build
SENTRYFLOW_ADMIN_PASSWORD=... docker compose --profile loadtest run --rm loadtest

# Other rates and durations
LOADTEST_RATE=1000 LOADTEST_DURATION=30s SENTRYFLOW_ADMIN_PASSWORD=... \
  docker compose --profile loadtest run --rm loadtest
```

The full k6 summary is also written to `loadtest/results/summary.json`
(git-ignored).

## Results

Measured on 2026-09-24 against the compose stack: one gateway process (a
single uvicorn worker), Redis, Kafka, ClickHouse and Postgres all in Docker
Desktop on an Apple M4 Pro (12 CPUs, 7.6 GB given to Docker). Latency is
client-observed through the gateway, for the steady scenario only.

| Offered rate | Requests | Median | p95 | p99 | Max | Failures |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 200/s, 60 s | 12,001 | 1.5 ms | 2.3 ms | 2.9 ms | 8.7 ms | 0 |
| 500/s, 30 s | 15,001 | 1.0 ms | 2.0 ms | 4.6 ms | 27 ms | 0 |
| 1,000/s, 30 s | 30,001 | 0.7 ms | 1.4 ms | 2.7 ms | 33 ms | 0 |
| 1,250/s, 30 s | 37,501 | 0.8 ms | 2.1 ms | 9.8 ms | 62 ms | 0 |
| 1,500/s, 30 s | 45,001 | 0.8 ms | 3.0 ms | 24.9 ms | 72 ms | 0 |
| 2,000/s, 30 s | 22,064 served, 37,941 not sent | 1.7 s | 13.4 s | 13.8 s | 14.2 s | 0 |

In every run the throttled caller got **exactly 30** successful responses out
of ~225, and new events showed up in the analytics API within **0.1–2.1 s**,
bounded by the aggregator's 2-second flush interval.

### Reading the numbers

- **One worker holds p99 under 25 ms up to 1,500 requests/s**, and saturates
  somewhere between 1,500 and 2,000. At 2,000/s requests queue, latency climbs
  into seconds, and k6 cannot send the rest. That is the point to add pods: the
  Helm chart's HPA scales the gateway from 3 to 12 replicas, and all replicas
  share one Redis, so limits hold across them.
- **This measures gateway overhead, not a backend.** `/api/v1/hello` does no
  work, so the time is the gateway itself: two Redis round trips (cached key
  lookup, the Lua limiter script) and handing an event to the Kafka producer.
  A proxied upstream adds its own latency on top.
- **It is a laptop, not AWS.** There is no network hop, TLS or load balancer
  between k6 and the gateway, and every dependency shares the same machine.
  Treat the absolute numbers as the gateway's own cost, and the curve as the
  useful part.

### What the first run found

The first smoke run (20 requests/s) passed its thresholds, but p99 was 88 ms
and the maximum 227 ms, much slower than the median. The slow requests lined
up with the test's own sign-ups and logins. `bcrypt` costs about 200 ms of CPU
by design, and the auth routes ran it directly on the event loop, so each
login stalled every gateway request in flight on that worker. Hashing and
verification now run in the threadpool. After the fix, the steady scenario's
worst request at 200/s was 8.7 ms. `test_login_checks_the_password_off_the_event_loop`
fails if either call moves back onto the loop.
