// Helpers for rate-limit rules (GET/PUT /limits).

export const ALGORITHMS = [
  { value: 'sliding_window', label: 'Sliding window' },
  { value: 'token_bucket', label: 'Token bucket' },
];

export const MAX_LIMIT_VALUE = 1000000;

export function algorithmLabel(value) {
  const match = ALGORITHMS.find((a) => a.value === value);
  return match ? match.label : value || '—';
}

export function endpointLabel(endpoint) {
  return endpoint === '*' ? 'All endpoints' : endpoint;
}

// Stable display order: by user, the user's "*" rule first, then by path.
export function sortRules(rules) {
  if (!Array.isArray(rules)) return [];
  return [...rules].sort((a, b) => {
    const byUser = String(a.username ?? a.user_id ?? '').localeCompare(String(b.username ?? b.user_id ?? ''));
    if (byUser !== 0) return byUser;
    if (a.endpoint === '*' && b.endpoint !== '*') return -1;
    if (b.endpoint === '*' && a.endpoint !== '*') return 1;
    return String(a.endpoint).localeCompare(String(b.endpoint));
  });
}

function parseLimitValue(value) {
  const text = String(value ?? '').trim();
  if (!/^\d+$/.test(text)) return null;
  const n = Number(text);
  return n >= 1 && n <= MAX_LIMIT_VALUE ? n : null;
}

// Validates the rule form. Returns { payload } for PUT /limits, or { error }.
export function validateRuleInput(input) {
  const userId = String(input?.user_id ?? '').trim();
  if (!userId) return { error: 'Choose the user this rule applies to.' };

  const endpoint = String(input?.endpoint ?? '').trim();
  if (endpoint !== '*' && !endpoint.startsWith('/')) {
    return { error: 'Endpoint must be * (all endpoints) or an exact path starting with /, e.g. /api/v1/hello.' };
  }

  const requestsPerMinute = parseLimitValue(input?.requests_per_minute);
  if (requestsPerMinute === null) {
    return { error: `Requests per minute must be a whole number from 1 to ${MAX_LIMIT_VALUE.toLocaleString()}.` };
  }

  const burstCapacity = parseLimitValue(input?.burst_capacity);
  if (burstCapacity === null) {
    return { error: `Burst capacity must be a whole number from 1 to ${MAX_LIMIT_VALUE.toLocaleString()}.` };
  }

  if (!ALGORITHMS.some((a) => a.value === input?.algorithm)) {
    return { error: 'Choose an algorithm.' };
  }

  return {
    payload: {
      user_id: userId,
      endpoint,
      requests_per_minute: requestsPerMinute,
      burst_capacity: burstCapacity,
      algorithm: input.algorithm,
    },
  };
}
