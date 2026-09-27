import { algorithmLabel, endpointLabel, sortRules, validateRuleInput } from './limits';

const validInput = {
  user_id: 'u1',
  endpoint: '*',
  requests_per_minute: '120',
  burst_capacity: '20',
  algorithm: 'token_bucket',
};

describe('validateRuleInput', () => {
  test('builds the PUT /limits payload with numbers', () => {
    expect(validateRuleInput(validInput)).toEqual({
      payload: {
        user_id: 'u1',
        endpoint: '*',
        requests_per_minute: 120,
        burst_capacity: 20,
        algorithm: 'token_bucket',
      },
    });
  });

  test('accepts an exact path and trims it', () => {
    expect(validateRuleInput({ ...validInput, endpoint: ' /api/v1/hello ' }).payload.endpoint).toBe('/api/v1/hello');
  });

  test.each([
    [{ user_id: '' }, /user/i],
    [{ endpoint: 'api/v1/hello' }, /Endpoint/],
    [{ endpoint: '' }, /Endpoint/],
    [{ requests_per_minute: '0' }, /Requests per minute/],
    [{ requests_per_minute: '1000001' }, /Requests per minute/],
    [{ requests_per_minute: '1.5' }, /Requests per minute/],
    [{ burst_capacity: '' }, /Burst capacity/],
    [{ algorithm: 'fixed_window' }, /algorithm/],
  ])('rejects %p', (override, message) => {
    const result = validateRuleInput({ ...validInput, ...override });
    expect(result.payload).toBeUndefined();
    expect(result.error).toMatch(message);
  });

  test('accepts the bounds', () => {
    expect(validateRuleInput({ ...validInput, requests_per_minute: '1', burst_capacity: '1000000' }).payload).toBeTruthy();
  });
});

describe('rule display helpers', () => {
  test('sortRules orders by user, "*" first, then path', () => {
    const rules = [
      { id: 1, username: 'bob', endpoint: '/b' },
      { id: 2, username: 'alice', endpoint: '/z' },
      { id: 3, username: 'alice', endpoint: '*' },
      { id: 4, username: 'alice', endpoint: '/a' },
    ];
    expect(sortRules(rules).map((r) => r.id)).toEqual([3, 4, 2, 1]);
    expect(sortRules(undefined)).toEqual([]);
  });

  test('labels', () => {
    expect(algorithmLabel('sliding_window')).toBe('Sliding window');
    expect(algorithmLabel('token_bucket')).toBe('Token bucket');
    expect(endpointLabel('*')).toBe('All endpoints');
    expect(endpointLabel('/api/v1/hello')).toBe('/api/v1/hello');
  });
});
