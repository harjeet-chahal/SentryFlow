# Rate limiting

The limiter runs on every gateway request, after the API key has been resolved
to a user and before the handler runs. It limits each user on each endpoint
(request path) separately. All state lives in Redis, which every gateway
replica shares, so a limit holds across the whole fleet rather than per pod.

The code is in [`backend/limiter/rate_limiter.py`](../backend/limiter/rate_limiter.py),
and the rules API in [`backend/limiter/limits_router.py`](../backend/limiter/limits_router.py).

## Contents

- [Algorithms](#algorithms)
- [Rules](#rules)
- [Managing rules](#managing-rules)
- [Response headers](#response-headers)
- [What is stored in Redis](#what-is-stored-in-redis)
- [When Redis is down](#when-redis-is-down)
- [Testing](#testing)

---

## Algorithms

Each algorithm is one Lua script. Redis runs a script as a single step that
no other command can interleave with, so reading the counter, deciding and
writing it back is atomic. The same logic in Python would need a
`WATCH`/`MULTI` loop that retries whenever another request changes the key
first, which is exactly what happens when one caller sends many concurrent
requests.

Both scripts are deterministic. The current time and the sorted-set member
are generated in Python and passed in as arguments, never generated inside
Lua, so the scripts replicate safely.

### Sliding window (default)

At most *N* requests in any trailing window of 60 seconds.

Each caller and endpoint has a sorted set with one member per admitted
request, scored by its timestamp in milliseconds. For each request, the
script:

1. removes members older than the window (`ZREMRANGEBYSCORE`);
2. counts what is left (`ZCARD`);
3. if the count has reached the limit, rejects the request and works out
   when the oldest member will age out, which becomes `Retry-After`;
4. otherwise adds the request (`ZADD`) and sets the key to expire one window
   later (`PEXPIRE`), so idle callers cost nothing.

A rejected request is not added, so a caller who keeps retrying while
throttled does not extend their own lockout.

The window slides continuously. A fixed window, reset on the minute, lets a
caller send the limit just before the boundary and the limit again just after
it: twice the limit within a second or two. The sliding window cannot be
gamed that way. The price is memory: one member per admitted request in the
window, so up to the limit itself.

### Token bucket

A bucket holds up to `burst_capacity` tokens and refills at
`requests_per_minute / 60` tokens per second. Each request takes one token;
with none left, the request is rejected.

Each caller and endpoint has a hash with two fields, `tokens` and
`last_refill_ms`. There is no timer: the script adds the tokens earned since
the last request, capped at the capacity, then takes one if it can. A
missing key is a full bucket, so a new caller gets the whole burst.
`Retry-After` is the time until one token has refilled. The key expires after
twice the time it takes to refill from empty, and never sooner than 60
seconds.

The token bucket allows a burst above the steady rate, by design, and its
memory stays constant however much traffic a caller sends.

### Choosing one

Measured with k6 against the compose stack
([load-testing.md](load-testing.md#sliding-window-vs-token-bucket)):

| | Sliding window | Token bucket |
| --- | --- | --- |
| Admits | at most *N* requests in any trailing 60 s | a burst up to the capacity, then *N* per minute |
| Work per request | `O(log N)` | `O(1)` |
| Median latency at 1,000 req/s | 0.66–0.90 ms | 0.64–0.94 ms |
| Busy caller's key after 30 s | 4.2 MB at 1,000 req/s, 7.7 MB at 2,000 req/s | 186–187 bytes at any rate |
| Caller allowed 30, sending over 200 | exactly 30 admitted in every run | exactly 30 admitted in every run |

The two cost the same per request; memory is the real difference. A sliding
window holds one member per admitted request, so its size tracks the limit: a
caller allowed 60 a minute never costs more than 60 members. The load test's
busy caller had a limit of a million a minute, so every request was admitted
and stored. At 1,000 requests/s, a full minute of that is 60,000 members. For
callers with high limits and heavy traffic, prefer the token bucket.

---

## Rules

A rule sets one user's limit on one endpoint, or on all of that user's
endpoints with `*`. Rules live in the `rate_limits` table:

| Column | Meaning |
| --- | --- |
| `user_id` | whose limit it is |
| `endpoint` | an exact request path such as `/api/v1/hello`, or `*` |
| `requests_per_minute` | the limit; for the token bucket, the refill rate |
| `burst_capacity` | the bucket size; token bucket only |
| `algorithm` | `sliding_window` or `token_bucket` |

For each request, the gateway takes the first match from:

1. the user's rule for this exact path;
2. the user's `*` rule;
3. the global defaults, from the environment.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEFAULT_RATE_LIMIT` | `60` | requests per minute |
| `DEFAULT_BURST_CAPACITY` | `10` | token-bucket capacity |
| `DEFAULT_RATE_LIMIT_ALGORITHM` | `sliding_window` | algorithm |
| `DEFAULT_RATE_LIMIT_WINDOW` | `60` | sliding-window length in seconds, for every rule |
| `RATE_LIMIT_FAIL_OPEN` | `true` | what to do when Redis is unreachable; see [below](#when-redis-is-down) |

The window length applies to every sliding-window rule. It is 60 seconds by
default, which is what makes `requests_per_minute` literally per minute.

`python -m backend.setup_db` seeds a `*` rule with the defaults for the
`admin` account, which the dashboard then shows and lets you edit.

### Caching

The database is authoritative, but it stays off the request path. The
resolved rule is cached in Redis for 60 seconds. When a user has no rule, the
cache records that they use the defaults, so callers on defaults never query
the database either.

Changing or deleting a rule through `/limits` deletes every cached result for
that user, so the change applies from their next request. It has to clear
every endpoint the user has called, not one key: changing their `*` rule
changes what each of those endpoints resolves to. If Redis refuses the
eviction, the change still applies within 60 seconds, when the cache entries
expire.

---

## Managing rules

**In the dashboard.** The Rate Limit Monitor page lists the rules in force
and the defaults. Admins add, edit and delete rules there. The same page
charts allowed and throttled requests over time, and ranks throttling by
endpoint and (for admins) by user. Other users see only the rules that apply
to them, read-only.

**Through the API.** `GET /limits`, `PUT /limits` and
`DELETE /limits/{rule_id}`, documented in
[api.md](api.md#rate-limit-rules). Only admins can write. A customer who
could raise their own limit would not really have one.

```bash
# Give a user a burst of 20, refilling at 120 requests a minute, on one endpoint
curl -X PUT localhost:8000/limits \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"user_id": "…", "endpoint": "/api/v1/hello",
       "requests_per_minute": 120, "burst_capacity": 20, "algorithm": "token_bucket"}'
```

---

## Response headers

| Header | Sliding window | Token bucket |
| --- | --- | --- |
| `X-RateLimit-Limit` | requests allowed per window | bucket capacity |
| `X-RateLimit-Remaining` | requests left in the window | whole tokens left |
| `X-RateLimit-Reset` | Unix time: one window from now if allowed; when the oldest request ages out if rejected | Unix time at which the bucket is full again |
| `Retry-After` (on `429` only) | seconds until the oldest request ages out | seconds until one token has refilled |

A rejected request gets:

```
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1790253660
Retry-After: 12

{"detail": "Rate limit exceeded."}
```

Clients should wait for `Retry-After` rather than retry at once:

```python
import time

import requests


def get_with_retry(url, api_key, attempts=5):
    for _ in range(attempts):
        response = requests.get(url, headers={"x-api-key": api_key})
        if response.status_code != 429:
            return response
        time.sleep(int(response.headers.get("Retry-After", "1")))
    return response
```

---

## What is stored in Redis

| Key | Type | Holds | Expires |
| --- | --- | --- | --- |
| `rate:sliding_window:{user}:{endpoint}` | sorted set | one member per admitted request | one window after the last admitted request |
| `rate:token_bucket:{user}:{endpoint}` | hash | `tokens`, `last_refill_ms` | twice the time to refill from empty, at least 60 s |
| `ratelimit:cfg:{user}:{endpoint}` | string | the resolved rule, or a marker meaning "use the defaults" | 60 s |
| `apikey:{key}` | string | the key's user, or a marker meaning "no such key" | 1 hour; 60 s for unknown keys |

The algorithm is part of the counter's key, so switching a user to the other
algorithm starts them with fresh state instead of misreading the old one.

---

## When Redis is down

With `RATE_LIMIT_FAIL_OPEN=true`, the default, requests are served without
enforcement. Losing the rate limiter should weaken enforcement, not take the
API down. Set it to `false` where over-admission is worse than downtime:
requests are then rejected with `429` and `Retry-After: 1`.

Either way, the `X-RateLimit-*` headers are left out of the response. A
limit of `0` would read as "you have no quota", and clients throttle
themselves on these headers, when the truth is that nothing was enforced.

Authentication never fails open. If Redis cannot answer, API keys are looked
up in the database on every request: slower, but still correct.

---

## Testing

- [`backend/tests/test_rate_limiter.py`](../backend/tests/test_rate_limiter.py)
  (35 tests) runs both Lua scripts in `fakeredis`, which executes real Lua.
  It covers:
  - the window boundary, where a fixed window would allow a double burst;
  - refill, and capping at the bucket's capacity;
  - `Retry-After` and reset times;
  - the order in which rules resolve, and caching them, including the
    "no rule" result;
  - evicting a user's cached rules;
  - failing open, and failing closed.
- [`backend/tests/test_limits.py`](../backend/tests/test_limits.py) (19
  tests) covers the rules API:
  - who may read and who may write;
  - validation, and two admins creating the same rule at once;
  - a lowered limit, or a deleted rule, taking effect on the very next
    request through the gateway.
- [`loadtest/gateway.js`](../loadtest/gateway.js) checks exactness under real
  concurrency for either algorithm. It also checks the token bucket's refill
  ([load-testing.md](load-testing.md)).
