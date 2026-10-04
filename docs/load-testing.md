# Load testing

`loadtest/gateway.js` is a [k6](https://k6.io) script that drives the gateway
and checks three properties at once, or four for the token bucket.
`ALGORITHM` picks the limiter every test caller gets: `sliding_window` (the
default) or `token_bucket`.

| Scenario | What it does | Pass condition |
| --- | --- | --- |
| **steady** | `RATE` requests/s for `DURATION` through the full gateway path: the token check, the limiter's Lua script in Redis, the handler, and the Kafka usage event | p95 **and** p99 under 100 ms; under 0.1% failures |
| **throttle** | one caller allowed 30 requests sends 5/s from several VUs for 45 s. The sliding window allows 30 per minute. The token bucket holds 30 tokens and refills at 1 per minute, which adds less than one token in 45 s | exactly 30 succeed; every other response is a 429 with `Retry-After` |
| **refill** | token bucket only. A caller with a 10-token bucket refilling at 1/s sends 20 requests at once, waits 5.5 s, and sends 20 more | exactly 10, then exactly 5, succeed |
| **freshness** | mid-run, a new user sends 20 requests and polls `/analytics/usage` until they appear | visible in under 10 s |

The thresholds are the pass/fail gate: k6 exits non-zero if any is missed.

## Running it

k6 runs from its container on the compose network, so it measures the gateway
rather than Docker Desktop's port forwarding. Setup signs up throwaway users,
trades their API keys for gateway tokens and sets their limits through the
admin API, so it needs the admin password (`docker compose logs migrate`
shows a generated one). The tokens are minted once, in setup, and last
`GATEWAY_TOKEN_EXPIRE_MINUTES` (15 by default), so setup fails early if
`DURATION` would outlast them.

```bash
docker compose up -d --build
SENTRYFLOW_ADMIN_PASSWORD=... docker compose --profile loadtest run --rm loadtest

# Other rates and durations
LOADTEST_RATE=1000 LOADTEST_DURATION=30s SENTRYFLOW_ADMIN_PASSWORD=... \
  docker compose --profile loadtest run --rm loadtest

# The token bucket instead of the sliding window
LOADTEST_ALGORITHM=token_bucket SENTRYFLOW_ADMIN_PASSWORD=... \
  docker compose --profile loadtest run --rm loadtest
```

The full k6 summary is also written to `loadtest/results/summary.json`
(git-ignored).

## Results

Measured on 2026-09-27 against the compose stack at `fb31636`, with JWT
authentication and usage events queued for a background Kafka publisher: one
gateway process (a single uvicorn worker), Redis, Kafka, ClickHouse and
Postgres all in Docker Desktop on an Apple M4 Pro (12 CPUs, 7.6 GB given to
Docker). The macOS Bluetooth daemon used about one core throughout. Latency is
client-observed through the gateway, for the steady scenario only. Rows are in
the order they ran; at 1,000/s the two algorithms took turns, twice each.

| Offered rate | Algorithm | Requests | Median | p95 | p99 | Max | Failures |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 200/s, 60 s | sliding window | 12,001 | 1.49 ms | 2.64 ms | 4.25 ms | 50 ms | 0 |
| 500/s, 30 s | sliding window | 15,001 | 0.93 ms | 1.31 ms | 1.87 ms | 12 ms | 0 |
| 1,000/s, 30 s | sliding window | 30,000 | 0.68 ms | 1.29 ms | 2.85 ms | 50 ms | 0 |
| 1,000/s, 30 s | token bucket | 30,002 | 0.80 ms | 1.87 ms | 5.79 ms | 35 ms | 0 |
| 1,000/s, 30 s | sliding window | 30,003 | 0.93 ms | 1.88 ms | 4.42 ms | 54 ms | 0 |
| 1,000/s, 30 s | token bucket | 30,001 | 0.64 ms | 1.18 ms | 2.75 ms | 35 ms | 0 |
| 1,250/s, 30 s | sliding window | 37,501 | 0.76 ms | 1.91 ms | 6.08 ms | 62 ms | 0 |
| 1,500/s, 30 s | sliding window | 45,001 | 0.76 ms | 2.82 ms | 10.5 ms | 48 ms | 0 |
| 2,000/s, 30 s | sliding window | 46,757 served, 13,255 not sent | 0.32 s | 4.0 s | 4.7 s | 5.3 s | 0 |

In every run the throttled caller got **exactly 30** successful responses out
of 215–226, and both token-bucket runs passed the refill check exactly: 10,
then 5. Below saturation, new events showed up in the analytics API within
**0.6–2.2 s**, bounded by the aggregator's 2-second flush interval. At 2,000/s
the freshness check never started: signing up its user timed out.

### Reading the numbers

- **One worker holds p99 under 11 ms up to 1,500 requests/s**, and saturates
  somewhere between 1,500 and 2,000. At 2,000/s requests queue, latency climbs
  into seconds, and k6 could not send 13,255 requests. The gateway's event
  queue filled and dropped 9,444 usage events rather than hold requests, as
  designed. That is the point to add pods: the Helm chart's HPA scales the
  gateway from 3 to 12 replicas, and all replicas share one Redis, so limits
  hold across them.
- **The two algorithms cost the same.** Their medians at 1,000/s overlap:
  0.68 and 0.93 ms for the sliding window, 0.80 and 0.64 ms for the token
  bucket. Their memory does not. After a 30 s run at 1,000/s, the busy
  caller's sliding-window key held 4.0 MB and its token-bucket key 170 bytes.
  The sliding window's key grows with traffic: 6.2 MB after 30 s at 1,500/s.
- **This measures gateway overhead, not a backend.** `/api/v1/hello` does no
  work, so the time is the gateway itself: a JWT signature check, three Redis
  round trips (the revocation check, the cached rule lookup and the Lua
  limiter script) and queueing an event for the Kafka publisher.
  A proxied upstream adds its own latency on top.
- **It is a laptop, not AWS.** There is no network hop, TLS or load balancer
  between k6 and the gateway, and every dependency shares the same machine.
  Treat the absolute numbers as the gateway's own cost, and the curve as the
  useful part.

### Earlier runs

The first published runs, on 2026-09-24, authenticated with API keys and
awaited Kafka inside each request; the sections below price both changes.
Same laptop and stack, one sliding-window run per rate:

| Offered rate | Requests | Median | p95 | p99 | Max | Failures |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 200/s, 60 s | 12,001 | 1.5 ms | 2.3 ms | 2.9 ms | 8.7 ms | 0 |
| 500/s, 30 s | 15,001 | 1.0 ms | 2.0 ms | 4.6 ms | 27 ms | 0 |
| 1,000/s, 30 s | 30,001 | 0.7 ms | 1.4 ms | 2.7 ms | 33 ms | 0 |
| 1,250/s, 30 s | 37,501 | 0.8 ms | 2.1 ms | 9.8 ms | 62 ms | 0 |
| 1,500/s, 30 s | 45,001 | 0.8 ms | 3.0 ms | 24.9 ms | 72 ms | 0 |
| 2,000/s, 30 s | 22,064 served, 37,941 not sent | 1.7 s | 13.4 s | 13.8 s | 14.2 s | 0 |

The throttled caller got exactly 30 successes out of ~225 in every run, and
new events reached the analytics API within 0.1–2.1 s.

### What the first run found

The first smoke run (20 requests/s) passed its thresholds, but p99 was 88 ms
and the maximum 227 ms, much slower than the median. The slow requests lined
up with the test's own sign-ups and logins. `bcrypt` costs about 200 ms of CPU
by design, and the auth routes ran it directly on the event loop, so each
login stalled every gateway request in flight on that worker. Hashing and
verification now run in the threadpool. After the fix, the steady scenario's
worst request at 200/s was 8.7 ms. `test_login_checks_the_password_off_the_event_loop`
fails if either call moves back onto the loop.

### The cost of queueing usage events

The 2026-09-24 runs predate usage events moving onto an in-memory queue,
which a background task publishes to Kafka (see [analytics](analytics.md)). The
queue adds one task switch per event. To price that, the steady scenario ran
on its own against the code before and after the change, alternating, on the
same laptop: the gateway under uvicorn on the host, with Redis and Kafka in
Docker, and k6 in Docker reaching the host through Docker Desktop. That path
differs from the compose network, so compare these rows with each other, not
with the tables above.

| Offered rate | Code | Median | p95 | p99 |
| ---: | --- | ---: | ---: | ---: |
| 1,000/s, 30 s | before | 1.38 ms | 2.03 ms | 3.3 ms |
| 1,000/s, 30 s | after | 1.38 ms | 2.00 ms | 3.8 ms |
| 1,500/s, 30 s, 3 runs | before | 1.92–1.94 ms | 3.1–3.8 ms | 6.9–9.9 ms |
| 1,500/s, 30 s, 3 runs | after | 1.96–2.00 ms | 3.4–3.8 ms | 8.3–16.1 ms |

There is no measurable cost at 1,000/s. At 1,500/s, where one worker is close
to saturation, the median rises by about 0.05 ms and p99 trends higher within
run-to-run noise. In exchange, a broker outage no longer holds each request
for up to 40 seconds.

### Sliding window vs token bucket

Measured on 2026-09-27 against the compose stack, before the switch to JWTs,
on the same laptop as above. Each run's callers used one algorithm, set with
`ALGORITHM`. The algorithms took turns, twice each at every rate, so both saw
the same conditions. The machine was busier than on 2026-09-24: iCloud Drive
sync and the Bluetooth daemon used about three cores throughout. That noise
shows up in p95 and p99 for both algorithms, so compare these rows with each
other, not with the tables above.

| Offered rate, 30 s | Algorithm | Median | p95 | p99 | Failures |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1,000/s | sliding window | 0.66, 0.90 ms | 1.7, 1.8 ms | 13.7, 5.0 ms | 0 |
| 1,000/s | token bucket | 0.64, 0.94 ms | 1.3, 1.8 ms | 10.8, 7.9 ms | 0 |
| 1,500/s | sliding window | 0.80, 0.78 ms | 6.4, 25.5 ms | 34.9, 94.3 ms | 0 |
| 1,500/s | token bucket | 0.87, 0.74 ms | 5.0, 2.6 ms | 21.3, 16.6 ms | 0 |
| 2,000/s | sliding window | 3.2 ms, 3.8 s | 104 ms, 5.1 s | 135 ms, 5.1 s | 0 |
| 2,000/s | token bucket | 2.5 s, 3.0 s | 5.0 s, 4.8 s | 6.2 s, 4.9 s | 0 |

- **Same cost per request.** Medians match at every rate, and at 1,000/s the
  tails match too. At 1,500/s the token bucket's p95 and p99 were lower in
  both pairs. That fits it doing less work in Redis, but two pairs on a busy
  machine are not enough to call it.
- **Same ceiling.** One worker tops out between 1,500 and 2,000 requests/s
  with either algorithm. At 2,000/s, three of the four runs fell behind:
  requests queued, latency reached seconds, and k6 could not send 27,000–28,000
  requests. The fourth, a sliding-window run, just kept up with a p99 of
  135 ms. One more token-bucket run with the refill scenario removed fell
  behind the same way, so the refill bursts were not the cause. At that rate,
  chance decides whether a run keeps up, not the algorithm. The three runs
  where dropped usage events were counted all fell behind. Each dropped
  between 17,277 and 18,218 events once the gateway's event queue filled, as
  designed.
- **Both exact.** In all twelve runs the throttled caller got exactly 30
  successes out of 209–226 requests. Every token-bucket run below saturation
  passed the refill check exactly: 10, then 5. At 2,000/s it let 8 through
  instead of 5, because the overloaded gateway spread the second burst over
  seconds and more tokens had refilled by the time those requests were checked.
- **Memory is the real difference.** The sliding window keeps one sorted-set
  member per admitted request in the window. The busy caller's limit was a
  million a minute, so every request was kept. After 30 s its key held
  4.2 MB at 1,000/s, 6.1–6.4 MB at 1,500/s and 7.7 MB at 2,000/s. A full
  minute of traffic doubles that, and it is per caller. The size is bounded by
  the limit, so it only matters for callers with high limits. The token
  bucket's key was 186–187 bytes in every run.

### API keys vs JWTs

Until 2026-09-27 the gateway authenticated each request by looking its API
key up in Redis. It now takes a JWT, which it verifies in-process, plus one
Redis call to check that the token's key has not been revoked since. That is
the same number of round trips as before; the new work is verifying the
token. To price it, the steady scenario ran against the code before and after,
alternating, on the same laptop: the gateway under uvicorn on the host with
SQLite, Redis in Docker, and k6 in Docker reaching the host through Docker
Desktop. There was no Kafka or ClickHouse, so usage events were dropped once
the queue filled and the freshness scenario could not pass. Compare these
rows with each other, not with the tables above.

| Offered rate, 30 s | Authentication | Median | p95 | p99 | Failures |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1,000/s | API key | 1.48, 1.47 ms | 2.07, 2.21 ms | 4.6, 5.7 ms | 0 |
| 1,000/s | JWT | 1.55, 1.53 ms | 2.25, 2.24 ms | 5.3, 5.2 ms | 0 |

- **About 0.06 ms at the median.** Both pairs agree on that; p95 and p99 moved
  within run-to-run noise. Timed on its own against the same Redis, the token
  check took about 20 µs longer than the key lookup it replaced, and verifying
  the signature accounts for 7 µs of that.
- **Still exact.** The throttled caller got exactly 30 successes in every run.
  A fifth run, JWTs with the token bucket, passed the refill check: 10, then 5.
