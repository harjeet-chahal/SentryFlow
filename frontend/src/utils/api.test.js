import { getJson, formatApiDetail, describeApiError, apiErrorMessage } from './api';

const httpError = (status, detail) => ({
  response: { status, data: detail === undefined ? {} : { detail } },
});

describe('getJson', () => {
  test('returns the JSON body and passes params and signal through', async () => {
    const client = { get: jest.fn().mockResolvedValue({ data: { ok: true } }) };
    const signal = new AbortController().signal;
    await expect(getJson(client, '/analytics/usage', { params: { range: '1h' }, signal })).resolves.toEqual({
      ok: true,
    });
    expect(client.get).toHaveBeenCalledWith('/analytics/usage', { params: { range: '1h' }, signal });
  });

  test('accepts JSON arrays', async () => {
    const client = { get: jest.fn().mockResolvedValue({ data: [] }) };
    await expect(getJson(client, '/auth/apikeys')).resolves.toEqual([]);
  });

  test('rejects an HTML page (e.g. the SPA fallback) as a bad response', async () => {
    const client = { get: jest.fn().mockResolvedValue({ data: '<!doctype html><html></html>' }) };
    const error = await getJson(client, '/analytics/usage').catch((err) => err);
    expect(error.kind).toBe('bad_response');
    expect(describeApiError(error).title).toBe('Unexpected response from the API');
  });
});

describe('formatApiDetail', () => {
  test('strings pass through', () => {
    expect(formatApiDetail('User not found')).toBe('User not found');
  });

  test('FastAPI validation errors are flattened', () => {
    const detail = [
      { loc: ['body', 'requests_per_minute'], msg: 'ensure this value is less than or equal to 1000000' },
      { loc: ['body', 'algorithm'], msg: 'unexpected value' },
    ];
    expect(formatApiDetail(detail)).toBe(
      'requests_per_minute: ensure this value is less than or equal to 1000000; algorithm: unexpected value'
    );
  });

  test('empty detail', () => {
    expect(formatApiDetail(undefined)).toBe('');
    expect(formatApiDetail(null)).toBe('');
  });
});

describe('describeApiError', () => {
  test('503 is explained as the analytics store being down', () => {
    const info = describeApiError(httpError(503, 'Analytics store unavailable'));
    expect(info.kind).toBe('unavailable');
    expect(info.title).toMatch(/temporarily unavailable/i);
  });

  test('403, 404 and 422 use the API detail', () => {
    expect(describeApiError(httpError(403, 'Admins only')).message).toBe('Admins only');
    expect(describeApiError(httpError(404, 'User not found')).kind).toBe('not_found');
    const invalid = describeApiError(httpError(422, [{ loc: ['query', 'range'], msg: 'bad range' }]));
    expect(invalid.kind).toBe('invalid');
    expect(invalid.message).toBe('range: bad range');
  });

  test('no response means the API is unreachable', () => {
    expect(describeApiError({ request: {}, message: 'Network Error' }).kind).toBe('network');
  });

  test('other statuses are generic', () => {
    const info = describeApiError(httpError(500));
    expect(info.kind).toBe('server');
    expect(info.message).toMatch(/HTTP 500/);
  });

  test('null error', () => {
    expect(describeApiError(null)).toBeNull();
  });
});

describe('apiErrorMessage', () => {
  test('prefers the API detail', () => {
    expect(apiErrorMessage(httpError(404, 'User not found'))).toBe('User not found');
  });

  test('falls back to the description', () => {
    expect(apiErrorMessage(httpError(500))).toMatch(/Something went wrong/);
    expect(apiErrorMessage(httpError(503, 'Analytics store unavailable'))).toMatch(/temporarily unavailable/);
  });
});
