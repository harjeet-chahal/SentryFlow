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

Requires a bearer token. Returns the authenticated user.

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

Any path that is not under `/auth`, `/health`, or the docs requires an API
key and is rate limited.

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
usage logging is fire-and-forget and the gateway still serves traffic.

See [deployment](deployment.md#probes) for why the three differ.

---

## Not yet implemented

The dashboard currently renders generated data for these views; the endpoints
are specified but not built:

- `GET /analytics/usage` — request counts, latency percentiles, error rates
- `GET /analytics/rate-limits` — throttling by user and endpoint
- `GET /rate-limits`, `PUT /rate-limits` — manage limits from the dashboard
  (limits are read from the `rate_limits` table today, so this is CRUD over
  an existing model)
