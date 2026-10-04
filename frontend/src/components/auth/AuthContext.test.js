import React from 'react';
import { render, waitFor, act } from '@testing-library/react';
import axios, { AxiosError } from 'axios';
import { AuthProvider, useAuth, API_URL } from './AuthContext';

// An unsigned JWT is enough: the client only decodes it to read `exp`.
const fakeJwt = (payload) => `${btoa('{"alg":"none"}')}.${btoa(JSON.stringify(payload))}.sig`;

const renderProvider = () => {
  const seen = [];
  const Probe = () => {
    seen.push(useAuth());
    return null;
  };
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );
  return { seen, latest: () => seen[seen.length - 1] };
};

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('API_URL', () => {
  const original = process.env.REACT_APP_API_URL;
  const loadApiUrl = (value) => {
    if (value === undefined) delete process.env.REACT_APP_API_URL;
    else process.env.REACT_APP_API_URL = value;
    let url;
    jest.isolateModules(() => {
      url = require('./AuthContext').API_URL;
    });
    return url;
  };

  afterEach(() => {
    if (original === undefined) delete process.env.REACT_APP_API_URL;
    else process.env.REACT_APP_API_URL = original;
  });

  test('defaults to localhost when REACT_APP_API_URL is unset', () => {
    expect(loadApiUrl(undefined)).toBe('http://localhost:8000');
  });

  test('an empty REACT_APP_API_URL means same-origin (relative) requests', () => {
    expect(loadApiUrl('')).toBe('');
  });

  test('an explicit REACT_APP_API_URL is used as is', () => {
    expect(loadApiUrl('https://api.example.test')).toBe('https://api.example.test');
  });
});

test('authAxios targets the API URL and is created only once', async () => {
  const { seen, latest } = renderProvider();

  await waitFor(() => expect(latest().loading).toBe(false));
  expect(seen.length).toBeGreaterThan(1);
  expect(new Set(seen.map((ctx) => ctx.authAxios)).size).toBe(1);
  expect(latest().authAxios.defaults.baseURL).toBe(API_URL);
});

test('a 401 refreshes the token once and retries through the same instance', async () => {
  localStorage.setItem('accessToken', fakeJwt({ sub: 'root', exp: Date.now() / 1000 + 3600 }));
  localStorage.setItem('refreshToken', 'refresh-1');
  jest.spyOn(axios, 'get').mockResolvedValue({ data: { id: 'a1', username: 'root', is_admin: true } });
  const post = jest
    .spyOn(axios, 'post')
    .mockResolvedValue({ data: { access_token: 'access-2', refresh_token: 'refresh-2' } });

  const { latest } = renderProvider();
  await waitFor(() => expect(latest().isAuthenticated).toBe(true));
  expect(latest().isAdmin).toBe(true);

  const { authAxios } = latest();
  const requests = [];
  authAxios.defaults.adapter = (config) => {
    requests.push({ url: config.url, baseURL: config.baseURL, auth: config.headers.Authorization });
    if (requests.length === 1) {
      const response = { status: 401, statusText: 'Unauthorized', data: {}, headers: {}, config };
      return Promise.reject(new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, null, response));
    }
    return Promise.resolve({ status: 200, statusText: 'OK', data: { ok: true }, headers: {}, config });
  };

  let response;
  await act(async () => {
    response = await authAxios.get('/analytics/usage', { params: { range: '1h' } });
  });

  expect(response.data).toEqual({ ok: true });
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith(`${API_URL}/auth/refresh`, { refresh_token: 'refresh-1' });
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual({ url: '/analytics/usage', baseURL: API_URL, auth: 'Bearer access-2' });
  expect(localStorage.getItem('accessToken')).toBe('access-2');
});

test('a failed refresh logs the user out and rejects the request', async () => {
  localStorage.setItem('accessToken', fakeJwt({ sub: 'alice', exp: Date.now() / 1000 + 3600 }));
  localStorage.setItem('refreshToken', 'refresh-1');
  jest.spyOn(axios, 'get').mockResolvedValue({ data: { id: 'u1', username: 'alice', is_admin: false } });
  jest.spyOn(axios, 'post').mockRejectedValue(new Error('refresh rejected'));
  jest.spyOn(console, 'error').mockImplementation(() => {});

  const { latest } = renderProvider();
  await waitFor(() => expect(latest().isAuthenticated).toBe(true));
  expect(latest().isAdmin).toBe(false);

  const { authAxios } = latest();
  authAxios.defaults.adapter = (config) => {
    const response = { status: 401, statusText: 'Unauthorized', data: {}, headers: {}, config };
    return Promise.reject(new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, null, response));
  };

  let failure;
  await act(async () => {
    failure = await authAxios.get('/analytics/usage').catch((err) => err);
  });

  expect(failure.response.status).toBe(401);
  expect(latest().isAuthenticated).toBe(false);
  expect(localStorage.getItem('accessToken')).toBeNull();
});
