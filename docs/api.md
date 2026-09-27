# API reference

Base URL: `http://localhost:8000`. Interactive docs are served at `/docs`.

## Two credentials

| | Used by | Header | Obtained from |
| --- | --- | --- | --- |
| **JWT** | the dashboard, a human | `Authorization: Bearer <token>` | `POST /auth/login` |
| **API key** | machine callers, through the gateway | `x-api-key: <key>` | `POST /auth/apikeys/create` |

They are not interchangeable. A JWT manages the account; an API key is what
the rate limiter meters. Tokens carry a `type` claim, so a refresh token is
rejected wherever an access token is required.

### Roles

| | Sees | Can change rate limits |
| --- | --- | --- |
| **User** | their own traffic and limits | no |
| **Admin** | every user's traffic, or one user's | yes |

Nobody signs up as an admin. `setup_db` creates the `admin` account, and
`python -m backend.setup_db --grant-admin <username>` promotes an existing one.
A user asking for someone else's data gets `403`, not an empty result.

---

## Authentication

### `POST /auth/signup`

```json
{ "username": "demo", "email": "demo@example.com", "password": "demo-password" }
```

`201` with the created user. `400` if the username or email is taken, `422`
if the email is malformed.

### `POST /auth/login`

**Form-encoded**, not JSON — this is the OAuth2 password flow, which is what
Swagger's Authorize button and standard client libraries speak.

```bash
curl -X POST localhost:8000/auth/login \
  -d 'username=demo&password=demo-password'
```

```json
{ "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
```

Access tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30);
refresh tokens after `REFRESH_TOKEN_EXPIRE_DAYS` (default 7). `401` on bad
credentials.

### `POST /auth/refresh`

```json
{ "refresh_token": "..." }
```

Returns a new pair. `401` if the token is invalid, expired, or an access
token rather than a refresh token.

### `GET /auth/me`

Requires a bearer token. Returns the authenticated user, including
`is_admin`, which the dashboard uses to decide what to show.

---

## API keys

All require `Authorization: Bearer <access_token>`.

### `POST /auth/apikeys/create`

```json
{ "name": "ci-pipeline" }
```

`201` with the key. The value is 32 bytes of hex entropy and is returned in
full on every read, so treat it as a secret.

### `GET /auth/apikeys`

Lists the caller's own keys. Never returns another user's.

### `DELETE /auth/apikeys/{api_key_id}`

`204` on success, `404` if the key does not exist or belongs to someone else.

Revocation deactivates the row **and** evicts the gateway's cache. Keys are
cached for `API_KEY_CACHE_TTL` (default 1h), so deactivating alone would
leave a revoked key working until the TTL lapsed.

---

## Gateway

Any path outside `/auth`, `/health`, `/analytics`, `/limits` and the docs
requires an API key and is rate limited. (The dashboard APIs are exempt from
the API key because they authenticate the person with a JWT instead.)

### `GET /api/v1/hello`

A minimal protected endpoint used to exercise the gateway path.

```bash
curl -i localhost:8000/api/v1/hello -H "x-api-key: $KEY"
```

### Response headers

| Header | Meaning |
| --- | --- |
| `X-RateLimit-Limit` | ceiling for this caller and endpoint |
| `X-RateLimit-Remaining` | requests left in the current window |
| `X-RateLimit-Reset` | Unix time at which full quota returns |
| `Retry-After` | seconds to wait; sent only on `429` |

While the limiter is degraded (Redis unreachable) the `X-RateLimit-*` headers
are omitted rather than reported as zero — zero would read as "no quota"
rather than "not enforced".

### Errors

| Status | Cause |
| --- | --- |
| `401` | missing, unknown or revoked API key |
| `429` | rate limit exceeded |

```json
{ "detail": "Rate limit exceeded." }
```

---

## Health

Unauthenticated, because Kubernetes probes cannot present credentials.

| Endpoint | Purpose | Checks |
| --- | --- | --- |
| `GET /health/live` | liveness probe | nothing |
| `GET /health/ready` | readiness probe | Postgres, Redis |
| `GET /health` | operator detail | Postgres, Redis, Kafka, with timings |

`/health/ready` returns `503` when a critical dependency is down. `/health`
returns `degraded` (still `200`) when only Kafka is unavailable, because
requests never wait on Kafka and the gateway still serves traffic. Its `kafka`
component counts usage events waiting for Kafka (`queued`), lost before
reaching it (`dropped`: queue full, or shut down first) and refused by it
(`failed`):

```json
{ "status": "unavailable", "detail": "Kafka is not accepting events",
  "queued": 5836, "dropped": 0, "failed": 78 }
```

See [deployment](deployment.md#probes) for why the three differ.

---

## Analytics

Read from ClickHouse, where the aggregator writes one row per gateway request.
All require a bearer token, take `range` (`1h`, `24h`, `7d`, `30d`; default
`24h`), and are scoped as described under [Roles](#roles): admins may pass
`user_id` to focus on one user.

| Range | Bucket | Points |
| --- | --- | --- |
| `1h` | 1 minute | 60 |
| `24h` | 1 hour | 24 |
| `7d` | 6 hours | 28 |
| `30d` | 1 day (UTC) | 30 |

Series are zero-filled — one point per bucket, with `t` the bucket start in
Unix seconds. The newest bucket is still filling, which is what makes the
charts live.

Two definitions apply everywhere:

- **errors** are 4xx and 5xx responses *excluding* 429. Throttling is counted
  separately as `rate_limited`, so a client hitting its limit does not read as
  the API failing.
- **latency** is gateway time (key lookup, limit check, handler) for served
  requests. 429s are excluded: they are turned away before the handler runs,
  so counting them would flatter every percentile. Buckets with no served
  requests report `null`, not `0`.

`503 {"detail": "Analytics store unavailable"}` if ClickHouse is down. The
gateway itself does not depend on ClickHouse.

### `GET /analytics/usage`

```json
{
  "range": "24h", "step_seconds": 3600,
  "scope": { "user_id": null, "username": null },
  "summary": {
    "requests": 1234, "errors": 12, "rate_limited": 30,
    "error_rate": 0.97, "rate_limited_rate": 2.43,
    "avg_ms": 1.6, "p50_ms": 1.0, "p95_ms": 2.8, "p99_ms": 3.0
  },
  "series": [
    { "t": 1790251200, "requests": 10, "errors": 0, "rate_limited": 1, "avg_ms": 1.2, "p95_ms": 2.0 }
  ],
  "status_codes": { "2xx": 1100, "3xx": 0, "4xx": 120, "5xx": 14 },
  "top_endpoints": [
    { "endpoint": "/api/v1/hello", "requests": 1000, "errors": 3, "rate_limited": 20, "p95_ms": 2.1 }
  ]
}
```

`scope.user_id` is `null` when an admin is looking at every user.
`status_codes` counts every response, 429s included under `4xx`.

### `GET /analytics/rate-limits`

```json
{
  "range": "24h", "step_seconds": 3600, "scope": { "user_id": "…", "username": "demo" },
  "totals": { "requests": 1234, "rate_limited": 30, "rate_limited_rate": 2.43 },
  "series": [ { "t": 1790251200, "allowed": 9, "rate_limited": 1 } ],
  "by_endpoint": [ { "endpoint": "/api/v1/hello", "requests": 1000, "rate_limited": 20 } ],
  "by_user": [ { "user_id": "…", "username": "demo", "requests": 500, "rate_limited": 20 } ]
}
```

`by_user` ranks the most-throttled users and is only filled for an admin
looking at everyone.

### `GET /analytics/logs`

The newest matching requests, newest first. Filters run in ClickHouse:

| Parameter | |
| --- | --- |
| `range` | default `1h` |
| `status` | `all`, `2xx`, `3xx`, `4xx`, `5xx` |
| `endpoint` | case-insensitive substring |
| `user_id` | admins only |
| `limit` | 1–1000, default 200 |

```json
{
  "range": "1h", "limit": 200, "truncated": true,
  "rows": [
    { "timestamp": "2026-09-24T12:00:05Z", "user_id": "…", "username": "demo",
      "endpoint": "/api/v1/hello", "status_code": 429, "response_time_ms": 1 }
  ]
}
```

`truncated` is `true` when more rows matched than were returned.

### `GET /analytics/users`

Admins only. Every account with its traffic in the range, busiest first;
accounts with no traffic are included with zeros and `last_seen: null`.

```json
{ "range": "24h", "users": [
  { "id": "…", "username": "demo", "email": "demo@example.com", "is_active": true,
    "is_admin": false, "requests": 500, "errors": 2, "rate_limited": 20,
    "p95_ms": 2.4, "last_seen": 1790253600 }
] }
```

---

## Rate-limit rules

A rule sets one user's limit on one endpoint, or on every endpoint with
`"endpoint": "*"`. The gateway resolves a request by exact endpoint, then the
user's `*` rule, then the global defaults. Changes apply on the **next**
request: writes evict the gateway's cached resolution for that user rather
than waiting for its 60-second TTL.

(These live at `/limits` rather than `/rate-limits` because the dashboard
serves its Rate Limit Monitor page at `/rate-limits` on the same origin.)

### `GET /limits`

Anyone signed in. Users see their own rules; admins see all, or one user's
with `?user_id=`.

```json
{
  "defaults": { "requests_per_minute": 60, "burst_capacity": 10,
                "algorithm": "sliding_window", "window_seconds": 60 },
  "rules": [
    { "id": "…", "user_id": "…", "username": "demo", "endpoint": "*",
      "requests_per_minute": 120, "burst_capacity": 20, "algorithm": "token_bucket",
      "updated_at": "2026-09-24T12:00:00+00:00" }
  ]
}
```

### `PUT /limits`

Admins only. Creates the rule for `(user_id, endpoint)`, or replaces it.

```json
{ "user_id": "…", "endpoint": "/api/v1/hello",
  "requests_per_minute": 120, "burst_capacity": 20, "algorithm": "sliding_window" }
```

| Field | Rule |
| --- | --- |
| `endpoint` | `*` or a path starting with `/`; default `*` |
| `requests_per_minute` | 1–1,000,000 |
| `burst_capacity` | 1–1,000,000, token bucket only; default 10 |
| `algorithm` | `sliding_window` (default) or `token_bucket` |

`200` with the rule. `403` for non-admins, `404` for an unknown user, `422`
for an invalid rule, `409` if another admin created the same rule at the same
moment.

### `DELETE /limits/{rule_id}`

Admins only. `204`; the user falls back to their next matching rule or the
defaults, immediately. `404` if the rule does not exist.
