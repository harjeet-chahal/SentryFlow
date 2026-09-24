// SentryFlow gateway load test (k6).
//
// Three scenarios run together:
//
//   steady     RATE requests/s for DURATION through the full gateway path:
//              API-key lookup, the sliding-window Lua script in Redis, the
//              handler, and the Kafka usage event. Its latency is the number
//              the thresholds gate on.
//   throttle   One caller limited to THROTTLE_LIMIT requests/minute, sending
//              far more than that from several VUs at once. Exactly
//              THROTTLE_LIMIT may succeed; every other request must be a 429
//              with Retry-After. This is the limiter's correctness check
//              under concurrency.
//   freshness  Mid-run, sends a handful of requests as a fresh user and times
//              how long until the analytics API reports them: the
//              gateway -> Kafka -> aggregator -> ClickHouse lag.
//
// Run it inside the compose network (see docs/load-testing.md):
//
//   docker compose --profile loadtest run --rm loadtest
//
// Setup signs up two users and raises/lowers their limits through the admin
// API, so it needs the seeded admin's password in ADMIN_PASSWORD.

import http from 'k6/http';
import { check, fail, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const RATE = Number(__ENV.RATE || 200);
const DURATION = __ENV.DURATION || '60s';
const ADMIN_USERNAME = __ENV.ADMIN_USERNAME || 'admin';
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD || '';
const THROTTLE_LIMIT = Number(__ENV.THROTTLE_LIMIT || 30);
// Kept inside one 60s window so the expected count is exact.
const THROTTLE_DURATION = '45s';
const FRESHNESS_REQUESTS = 20;

const throttleAllowed = new Counter('throttle_allowed');
const throttleRejected = new Counter('throttle_rejected');
const analyticsFreshness = new Trend('analytics_freshness_ms', true);

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-arrival-rate',
      exec: 'steady',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: Math.max(20, Math.ceil(RATE / 4)),
      maxVUs: Math.max(100, RATE * 2),
    },
    throttle: {
      executor: 'constant-arrival-rate',
      exec: 'throttle',
      rate: 5,
      timeUnit: '1s',
      duration: THROTTLE_DURATION,
      preAllocatedVUs: 5,
      maxVUs: 20,
    },
    freshness: {
      executor: 'shared-iterations',
      exec: 'freshness',
      vus: 1,
      iterations: 1,
      startTime: '20s',
      maxDuration: '60s',
    },
  },
  thresholds: {
    // The latency claim: well under 100 ms at the 95th and 99th percentile.
    'http_req_duration{scenario:steady}': ['p(95)<100', 'p(99)<100'],
    'http_req_failed{scenario:steady}': ['rate<0.001'],
    'checks{scenario:steady}': ['rate>0.999'],
    // The limiter admits exactly the limit, no more, under concurrency.
    throttle_allowed: [`count==${THROTTLE_LIMIT}`],
    'checks{scenario:throttle}': ['rate==1'],
    // Events reach the dashboard in seconds, not at the next batch of 1000.
    analytics_freshness_ms: ['max<10000'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function json(body) {
  return { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

function login(username, password) {
  const res = http.post(`${BASE_URL}/auth/login`, { username, password });
  if (res.status !== 200) fail(`login as ${username} failed: ${res.status} ${res.body}`);
  return res.json('access_token');
}

function bearer(token) {
  return { headers: { Authorization: `Bearer ${token}` } };
}

// Sign up a user and mint an API key for it.
function newCaller(prefix) {
  const username = `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const password = 'load-test-password';
  const { headers, body } = json({ username, email: `${username}@example.com`, password });
  const signup = http.post(`${BASE_URL}/auth/signup`, body, { headers });
  if (signup.status !== 201) fail(`signup failed: ${signup.status} ${signup.body}`);

  const token = login(username, password);
  const key = http.post(
    `${BASE_URL}/auth/apikeys/create`,
    JSON.stringify({ name: 'k6' }),
    { headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } },
  );
  if (key.status !== 201) fail(`api key creation failed: ${key.status} ${key.body}`);
  return { id: signup.json('id'), token, key: key.json('key') };
}

function setLimit(adminToken, userId, requestsPerMinute) {
  const res = http.put(
    `${BASE_URL}/limits`,
    JSON.stringify({ user_id: userId, endpoint: '*', requests_per_minute: requestsPerMinute, algorithm: 'sliding_window' }),
    { headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${adminToken}` } },
  );
  if (res.status !== 200) fail(`setting a limit failed: ${res.status} ${res.body}`);
}

export function setup() {
  if (!ADMIN_PASSWORD) {
    fail('Set ADMIN_PASSWORD to the seeded admin password (docker compose logs migrate).');
  }
  const admin = login(ADMIN_USERNAME, ADMIN_PASSWORD);

  // High enough that the steady scenario measures served requests, not 429s.
  const steady = newCaller('load');
  setLimit(admin, steady.id, 1000000);

  const throttled = newCaller('throttle');
  setLimit(admin, throttled.id, THROTTLE_LIMIT);

  return { steadyKey: steady.key, throttleKey: throttled.key };
}

export function steady(data) {
  const res = http.get(`${BASE_URL}/api/v1/hello`, { headers: { 'x-api-key': data.steadyKey } });
  check(res, {
    'served (200)': (r) => r.status === 200,
    'carries rate-limit headers': (r) => r.headers['X-Ratelimit-Limit'] !== undefined,
  });
}

export function throttle(data) {
  const res = http.get(`${BASE_URL}/api/v1/hello`, {
    headers: { 'x-api-key': data.throttleKey },
    // 429 is the expected outcome here, not a failure.
    responseCallback: http.expectedStatuses(200, 429),
  });
  if (res.status === 200) throttleAllowed.add(1);
  if (res.status === 429) throttleRejected.add(1);
  check(res, {
    'allowed or throttled': (r) => r.status === 200 || r.status === 429,
    '429 says when to retry': (r) => r.status !== 429 || Number(r.headers['Retry-After']) > 0,
  });
}

export function freshness() {
  const caller = newCaller('fresh');
  for (let i = 0; i < FRESHNESS_REQUESTS; i++) {
    http.get(`${BASE_URL}/api/v1/hello`, { headers: { 'x-api-key': caller.key } });
  }
  const sentAt = Date.now();

  while (Date.now() - sentAt < 30000) {
    const res = http.get(`${BASE_URL}/analytics/usage?range=1h`, bearer(caller.token));
    if (res.status === 200 && res.json('summary.requests') >= FRESHNESS_REQUESTS) {
      analyticsFreshness.add(Date.now() - sentAt);
      return;
    }
    sleep(0.25);
  }
  fail('usage events did not reach the analytics API within 30s');
}
