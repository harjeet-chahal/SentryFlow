// Page-level tests against a stubbed API client that follows the backend contract.
import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { useAuth } from '../components/auth/AuthContext';
import Dashboard from './Dashboard';
import RateLimitMonitor from './RateLimitMonitor';
import LogsExplorer from './LogsExplorer';
import UserView from './UserView';
import ApiKeys from './ApiKeys';

jest.mock('../components/auth/AuthContext', () => ({
  useAuth: jest.fn(),
  API_URL: 'http://gateway.test',
  publicApiUrl: (path = '') => `http://gateway.test${path}`,
}));

// chart.js needs a real canvas; render labelled placeholders instead.
jest.mock('react-chartjs-2', () => {
  const mockReact = require('react');
  const chart = (type) => (props) =>
    mockReact.createElement('div', { 'data-testid': `${type}-chart`, 'aria-label': props['aria-label'] });
  return { Line: chart('line'), Bar: chart('bar'), Pie: chart('pie') };
});

const T0 = Date.UTC(2026, 8, 24, 10) / 1000;

const usage = (overrides = {}) => ({
  range: '24h',
  step_seconds: 3600,
  scope: { user_id: null, username: null },
  summary: {
    requests: 1234,
    errors: 12,
    rate_limited: 30,
    error_rate: 0.97,
    rate_limited_rate: 2.43,
    avg_ms: 3.2,
    p50_ms: 2,
    p95_ms: 8,
    p99_ms: 15,
  },
  series: [
    { t: T0, requests: 10, errors: 0, rate_limited: 1, avg_ms: 3.1, p95_ms: 7 },
    { t: T0 + 3600, requests: 0, errors: 0, rate_limited: 0, avg_ms: null, p95_ms: null },
  ],
  status_codes: { '2xx': 1100, '3xx': 0, '4xx': 120, '5xx': 14 },
  top_endpoints: [{ endpoint: '/api/v1/hello', requests: 1000, errors: 3, rate_limited: 20, p95_ms: 8 }],
  ...overrides,
});

const noTraffic = (overrides = {}) => usage({ summary: { ...usage().summary, requests: 0 }, ...overrides });

let routes;
let authAxios;

const respond = (data) => Promise.resolve({ status: 200, data });
const httpError = (status, detail) => Promise.reject({ response: { status, data: { detail } } });

const setAuth = ({ isAdmin }) => {
  useAuth.mockReturnValue({
    authAxios,
    isAdmin,
    user: { id: isAdmin ? 'admin' : 'u1', username: isAdmin ? 'root' : 'alice', is_admin: isAdmin },
  });
};

beforeEach(() => {
  routes = {};
  authAxios = {
    get: jest.fn((url, config) =>
      routes[url] ? routes[url](config) : Promise.reject(new Error(`Unexpected GET ${url}`))
    ),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  };
});

// Tests that trigger a refetch wait for its result to show up, so no state
// update lands after the test has finished.
const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true };

const logsCallParams = () =>
  authAxios.get.mock.calls.filter(([url]) => url === '/analytics/logs').map(([, config]) => config.params);

describe('Dashboard', () => {
  const renderDashboard = () =>
    render(
      <MemoryRouter future={ROUTER_FUTURE}>
        <Dashboard />
      </MemoryRouter>
    );

  test('shows the summary cards and charts from /analytics/usage', async () => {
    setAuth({ isAdmin: true });
    routes['/analytics/usage'] = () => respond(usage());
    renderDashboard();

    expect(await screen.findByText('Total requests')).toBeInTheDocument();
    expect(authAxios.get).toHaveBeenCalledWith(
      '/analytics/usage',
      expect.objectContaining({ params: { range: '24h' } })
    );
    expect(screen.getByText((1234).toLocaleString())).toBeInTheDocument();
    expect(screen.getByText('0.97%')).toBeInTheDocument();
    expect(screen.getByText('4xx/5xx, excluding 429')).toBeInTheDocument();
    expect(screen.getByText('avg 3.2 ms · p99 15 ms')).toBeInTheDocument();
    expect(screen.getByText('2.43% of requests')).toBeInTheDocument();
    expect(screen.getByText('All users')).toBeInTheDocument();
    expect(screen.getByText(/Live · updated \d\d:\d\d:\d\d/)).toBeInTheDocument();
    expect(screen.getByLabelText('Requests over time')).toBeInTheDocument();
    expect(screen.getByLabelText('Latency over time')).toBeInTheDocument();
    expect(screen.getByLabelText('Status code distribution')).toBeInTheDocument();
    expect(screen.getByLabelText('Top endpoints by requests')).toBeInTheDocument();
  });

  test('re-fetches when the time range changes', async () => {
    setAuth({ isAdmin: false });
    routes['/analytics/usage'] = ({ params }) =>
      respond(usage({ range: params.range, summary: { ...usage().summary, requests: params.range === '7d' ? 9876 : 1234 } }));
    renderDashboard();

    await screen.findByText('Total requests');
    expect(screen.getByText('Your API keys')).toBeInTheDocument();
    userEvent.click(screen.getByRole('button', { name: '7d' }));
    expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
    expect(await screen.findByText((9876).toLocaleString())).toBeInTheDocument();
    expect(authAxios.get).toHaveBeenLastCalledWith(
      '/analytics/usage',
      expect.objectContaining({ params: { range: '7d' } })
    );
  });

  test('explains how to generate traffic when the window is empty', async () => {
    setAuth({ isAdmin: false });
    routes['/analytics/usage'] = () => respond(noTraffic());
    renderDashboard();

    expect(await screen.findByText('No traffic in the last 24 hours yet')).toBeInTheDocument();
    expect(screen.getByText('curl -H "x-api-key: <key>" http://gateway.test/api/v1/hello')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'API Keys' })).toHaveAttribute('href', '/api-keys');
    expect(screen.queryByText('Total requests')).not.toBeInTheDocument();
  });

  test('shows a friendly message when the analytics store is down (503)', async () => {
    setAuth({ isAdmin: true });
    routes['/analytics/usage'] = () => httpError(503, 'Analytics store unavailable');
    renderDashboard();

    expect(await screen.findByText('Analytics are temporarily unavailable')).toBeInTheDocument();
    expect(screen.getByText(/Retrying automatically/)).toBeInTheDocument();
  });

  test('shows a generic error for other failures', async () => {
    setAuth({ isAdmin: true });
    routes['/analytics/usage'] = () => httpError(500);
    renderDashboard();

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument();
  });
});

describe('RateLimitMonitor', () => {
  const rateLimits = {
    range: '24h',
    step_seconds: 3600,
    scope: { user_id: null, username: null },
    totals: { requests: 60, rate_limited: 12, rate_limited_rate: 20 },
    series: [
      { t: T0, allowed: 40, rate_limited: 2 },
      { t: T0 + 3600, allowed: 8, rate_limited: 10 },
    ],
    by_endpoint: [{ endpoint: '/api/v1/hello', requests: 60, rate_limited: 12 }],
    by_user: [{ user_id: 'u1', username: 'alice', requests: 50, rate_limited: 12 }],
  };
  const limits = {
    defaults: { requests_per_minute: 60, burst_capacity: 10, algorithm: 'sliding_window', window_seconds: 60 },
    rules: [
      {
        id: 'r1',
        user_id: 'u1',
        username: 'alice',
        endpoint: '*',
        requests_per_minute: 120,
        burst_capacity: 20,
        algorithm: 'token_bucket',
        updated_at: '2026-09-24T12:00:00Z',
      },
    ],
  };
  const users = {
    range: '30d',
    users: [
      { id: 'u1', username: 'alice', email: 'a@x.com', is_active: true, is_admin: false },
      { id: 'u2', username: 'bob', email: 'b@x.com', is_active: true, is_admin: false },
    ],
  };

  let rules;

  beforeEach(() => {
    // Behaves like the server: PUT upserts on (user, endpoint), DELETE removes.
    rules = [...limits.rules];
    routes['/analytics/rate-limits'] = () => respond(rateLimits);
    routes['/limits'] = () => respond({ ...limits, rules });
    routes['/analytics/users'] = () => respond(users);
    authAxios.put.mockImplementation((url, body) => {
      const user = users.users.find((u) => u.id === body.user_id);
      const saved = { id: `r${rules.length + 1}`, username: user.username, updated_at: '2026-09-24T12:05:00Z', ...body };
      rules = [...rules.filter((r) => r.user_id !== body.user_id || r.endpoint !== body.endpoint), saved];
      return respond(saved);
    });
    authAxios.delete.mockImplementation((url) => {
      rules = rules.filter((r) => url !== `/limits/${r.id}`);
      return Promise.resolve({ status: 204 });
    });
  });

  test('non-admins get a read-only view of their limits', async () => {
    setAuth({ isAdmin: false });
    render(<RateLimitMonitor />);

    expect(await screen.findByText('120 req/min')).toBeInTheDocument();
    expect(screen.getByText(/Limits are set by an administrator/)).toBeInTheDocument();
    expect(screen.getByText('Global default')).toBeInTheDocument();
    expect(screen.getByText('60 req/min')).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'User' })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Method' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByText('Add or update a rule')).not.toBeInTheDocument();
    expect(await screen.findByLabelText('Allowed and rate-limited requests over time')).toBeInTheDocument();
    expect(screen.queryByText('Most throttled users')).not.toBeInTheDocument();
    expect(authAxios.get).not.toHaveBeenCalledWith('/analytics/users', expect.anything());
  });

  test('admins can create a rule', async () => {
    setAuth({ isAdmin: true });
    render(<RateLimitMonitor />);

    expect(await screen.findByText('Most throttled users')).toBeInTheDocument();
    // Both the most-throttled table and the rules table have a user column.
    await waitFor(() => expect(screen.getAllByRole('columnheader', { name: 'User' })).toHaveLength(2));
    await screen.findByRole('option', { name: 'bob (b@x.com)' });

    userEvent.selectOptions(screen.getByLabelText('User'), 'u2');
    const endpoint = screen.getByLabelText('Endpoint');
    userEvent.clear(endpoint);
    userEvent.type(endpoint, '/api/v1/hello');
    const rpm = screen.getByLabelText('Requests / minute');
    userEvent.clear(rpm);
    userEvent.type(rpm, '5');
    const burst = screen.getByLabelText('Burst capacity');
    userEvent.clear(burst);
    userEvent.type(burst, '2');
    userEvent.selectOptions(screen.getByLabelText('Algorithm'), 'token_bucket');
    userEvent.click(screen.getByRole('button', { name: 'Save rule' }));
    expect(authAxios.put).toHaveBeenCalledWith('/limits', {
      user_id: 'u2',
      endpoint: '/api/v1/hello',
      requests_per_minute: 5,
      burst_capacity: 2,
      algorithm: 'token_bucket',
    });

    // The rules table is reloaded and shows the new rule.
    expect(await screen.findByText('5 req/min')).toBeInTheDocument();
    expect(screen.getByText('Saved the /api/v1/hello rule for bob. It takes effect immediately.')).toBeInTheDocument();
  });

  test('client-side validation stops obviously bad input', async () => {
    setAuth({ isAdmin: true });
    render(<RateLimitMonitor />);

    await screen.findByRole('option', { name: 'bob (b@x.com)' });
    userEvent.click(screen.getByRole('button', { name: 'Save rule' }));
    expect(await screen.findByText('Choose the user this rule applies to.')).toBeInTheDocument();
    expect(authAxios.put).not.toHaveBeenCalled();
  });

  test('admins can edit and delete rules, and API errors are shown', async () => {
    setAuth({ isAdmin: true });
    authAxios.put.mockImplementation(() => httpError(404, 'User not found'));
    const confirm = jest.spyOn(window, 'confirm').mockReturnValue(true);
    render(<RateLimitMonitor />);

    userEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(screen.getByText('Edit the all-endpoints rule for alice')).toBeInTheDocument();
    expect(screen.getByLabelText('Endpoint')).toBeDisabled();
    expect(screen.getByLabelText('Endpoint')).toHaveValue('*');
    const rpm = screen.getByLabelText('Requests / minute');
    expect(rpm).toHaveValue(120);
    userEvent.clear(rpm);
    userEvent.type(rpm, '240');
    userEvent.click(screen.getByRole('button', { name: 'Update rule' }));
    expect(authAxios.put).toHaveBeenCalledWith('/limits', {
      user_id: 'u1',
      endpoint: '*',
      requests_per_minute: 240,
      burst_capacity: 20,
      algorithm: 'token_bucket',
    });
    expect(await screen.findByText('User not found')).toBeInTheDocument();

    userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(confirm).toHaveBeenCalled();
    expect(authAxios.delete).toHaveBeenCalledWith('/limits/r1');
    // The rules table is reloaded without the deleted rule.
    await waitFor(() => expect(screen.queryByText('120 req/min')).not.toBeInTheDocument());
    expect(screen.getByText('Deleted the all-endpoints rule for alice.')).toBeInTheDocument();
    confirm.mockRestore();
  });
});

describe('LogsExplorer', () => {
  const logs = {
    range: '1h',
    limit: 200,
    truncated: true,
    rows: [
      {
        timestamp: '2026-09-24T12:00:01Z',
        user_id: 'u1',
        username: 'alice',
        endpoint: '/api/v1/hello',
        status_code: 200,
        response_time_ms: 3,
      },
      {
        timestamp: '2026-09-24T12:00:00Z',
        user_id: 'u2',
        username: 'bob',
        endpoint: '/api/v1/hello',
        status_code: 429,
        response_time_ms: 1,
      },
    ],
  };

  // Filters like the server would. Unfiltered results report truncation.
  const serveLogs = ({ params }) => {
    const rows = logs.rows.filter(
      (row) =>
        (params.status === 'all' || `${Math.floor(row.status_code / 100)}xx` === params.status) &&
        (!params.endpoint || row.endpoint.includes(params.endpoint)) &&
        (!params.user_id || row.user_id === params.user_id)
    );
    return respond({ range: params.range, limit: params.limit, truncated: rows.length === logs.rows.length, rows });
  };

  test('admins see usernames and can filter by user; filtering is server-side', async () => {
    setAuth({ isAdmin: true });
    routes['/analytics/logs'] = serveLogs;
    routes['/analytics/users'] = () =>
      respond({ range: '30d', users: [{ id: 'u1', username: 'alice' }, { id: 'u2', username: 'bob' }] });
    render(<LogsExplorer />);

    expect(await screen.findByText('Showing the latest 2 matching requests in the last hour')).toBeInTheDocument();
    expect(logsCallParams()).toEqual([{ range: '1h', status: 'all', limit: 200 }]);
    expect(screen.getByRole('columnheader', { name: 'User' })).toBeInTheDocument();
    const rows = screen.getAllByRole('row');
    expect(within(rows[1]).getByText('alice')).toBeInTheDocument();
    expect(within(rows[1]).getByText('3 ms')).toBeInTheDocument();
    expect(within(rows[2]).getByText('429')).toBeInTheDocument();
    // A 429 still reports its gateway time (key lookup and limit check).
    expect(within(rows[2]).getByText('1 ms')).toBeInTheDocument();

    await screen.findByRole('option', { name: 'bob' });
    userEvent.selectOptions(screen.getByLabelText('User'), 'u2');
    userEvent.selectOptions(screen.getByLabelText('Status Code'), '4xx');
    expect(await screen.findByText('1 matching request in the last hour')).toBeInTheDocument();
    expect(logsCallParams()).toContainEqual({ range: '1h', status: '4xx', limit: 200, user_id: 'u2' });
  });

  test('non-admins get no user column or filter, and the endpoint filter is debounced', async () => {
    setAuth({ isAdmin: false });
    routes['/analytics/logs'] = serveLogs;
    render(<LogsExplorer />);

    expect(await screen.findByText('Showing the latest 2 matching requests in the last hour')).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'User' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('User')).not.toBeInTheDocument();

    userEvent.type(screen.getByLabelText('Endpoint'), '/other');
    expect(logsCallParams()).toHaveLength(1);
    expect(await screen.findByText('No requests match these filters in the last hour.')).toBeInTheDocument();
    expect(logsCallParams()).toContainEqual({ range: '1h', status: 'all', limit: 200, endpoint: '/other' });
    // Only the final value was sent, not every keystroke.
    expect(logsCallParams().filter((p) => p.endpoint)).toHaveLength(1);
    expect(authAxios.get).not.toHaveBeenCalledWith('/analytics/users', expect.anything());
  });

  test('the refresh button re-runs the query', async () => {
    setAuth({ isAdmin: false });
    const newer = { ...logs.rows[0], timestamp: '2026-09-24T12:00:02Z' };
    routes['/analytics/logs'] = () =>
      respond({ ...logs, truncated: false, rows: logsCallParams().length > 1 ? [newer, ...logs.rows] : logs.rows });
    render(<LogsExplorer />);

    expect(await screen.findByText('2 matching requests in the last hour')).toBeInTheDocument();
    userEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(await screen.findByText('3 matching requests in the last hour')).toBeInTheDocument();
    expect(logsCallParams()).toHaveLength(2);
  });
});

describe('UserView', () => {
  const renderUserView = () =>
    render(
      <MemoryRouter future={ROUTER_FUTURE}>
        <UserView />
      </MemoryRouter>
    );

  test('non-admins see a notice and nothing is fetched', () => {
    setAuth({ isAdmin: false });
    renderUserView();

    expect(screen.getByText('Only administrators can view per-user analytics')).toBeInTheDocument();
    expect(authAxios.get).not.toHaveBeenCalled();
  });

  test('admins pick a user to load that user’s usage', async () => {
    setAuth({ isAdmin: true });
    routes['/analytics/users'] = () =>
      respond({
        range: '24h',
        users: [
          {
            id: 'u1',
            username: 'alice',
            email: 'a@x.com',
            is_active: true,
            is_admin: false,
            requests: 500,
            errors: 2,
            rate_limited: 20,
            p95_ms: 8,
            last_seen: T0,
          },
          {
            id: 'u2',
            username: 'bob',
            email: 'b@x.com',
            is_active: false,
            is_admin: true,
            requests: 0,
            errors: 0,
            rate_limited: 0,
            p95_ms: null,
            last_seen: null,
          },
        ],
      });
    routes['/analytics/usage'] = (config) =>
      respond(config.params.user_id === 'u1' ? usage() : noTraffic({ scope: { user_id: 'u2', username: 'bob' } }));
    renderUserView();

    expect(await screen.findByText('Total requests')).toBeInTheDocument();
    expect(authAxios.get).toHaveBeenCalledWith(
      '/analytics/usage',
      expect.objectContaining({ params: { range: '24h', user_id: 'u1' } })
    );
    expect(screen.getByText('Never')).toBeInTheDocument();
    expect(screen.getByText('Inactive')).toBeInTheDocument();

    userEvent.click(screen.getByText('bob'));
    expect(await screen.findByText('bob made no requests in the last 24 hours.')).toBeInTheDocument();
    expect(authAxios.get).toHaveBeenCalledWith(
      '/analytics/usage',
      expect.objectContaining({ params: { range: '24h', user_id: 'u2' } })
    );
  });
});

describe('ApiKeys', () => {
  const activeKey = {
    id: 'k1',
    name: 'Production',
    key: 'abcdef1234567890abcdef',
    created_at: '2026-09-20T10:00:00.123456',
    last_used_at: null,
    is_active: true,
  };
  const revokedKey = {
    id: 'k2',
    name: 'Old key',
    key: 'zyxwvuts98765432',
    created_at: '2026-09-01T10:00:00',
    last_used_at: '2026-09-02T10:00:00',
    is_active: false,
  };

  test('lists keys masked, reveals on request, and marks revoked keys', async () => {
    setAuth({ isAdmin: false });
    routes['/auth/apikeys'] = () => respond([revokedKey, activeKey]);
    render(<ApiKeys />);

    expect(await screen.findByText('abcdef12…')).toBeInTheDocument();
    expect(screen.queryByText(activeKey.key)).not.toBeInTheDocument();

    const rows = screen.getAllByRole('row');
    expect(within(rows[1]).getByText('Production')).toBeInTheDocument();
    expect(within(rows[1]).getByText('Never')).toBeInTheDocument();
    expect(within(rows[2]).getByText('Revoked')).toBeInTheDocument();
    expect(within(rows[2]).queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument();

    userEvent.click(within(rows[1]).getByRole('button', { name: 'Reveal' }));
    expect(screen.getByText(activeKey.key)).toBeInTheDocument();
  });

  test('revokes a key only after confirmation', async () => {
    setAuth({ isAdmin: false });
    let revoked = false;
    routes['/auth/apikeys'] = () => respond([{ ...activeKey, is_active: !revoked }]);
    authAxios.delete.mockImplementation(() => {
      revoked = true;
      return Promise.resolve({ status: 204 });
    });
    const confirm = jest.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<ApiKeys />);

    const revoke = await screen.findByRole('button', { name: 'Revoke' });
    userEvent.click(revoke);
    expect(authAxios.delete).not.toHaveBeenCalled();

    userEvent.click(revoke);
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(authAxios.delete).toHaveBeenCalledWith('/auth/apikeys/k1');
    expect(await screen.findByText('Revoked')).toBeInTheDocument();
    confirm.mockRestore();
  });

  test('creating a key shows the full key with a copy button', async () => {
    setAuth({ isAdmin: false });
    let keys = [];
    routes['/auth/apikeys'] = () => respond(keys);
    authAxios.post.mockImplementation((url, body) => {
      keys = [{ ...activeKey, name: body.name }];
      return Promise.resolve({ status: 201, data: keys[0] });
    });
    render(<ApiKeys />);

    await screen.findByText(/No API keys yet/);
    userEvent.type(screen.getByLabelText('Key Name'), 'CI key');
    userEvent.click(screen.getByRole('button', { name: 'Create API Key' }));
    expect(authAxios.post).toHaveBeenCalledWith('/auth/apikeys/create', { name: 'CI key' });

    // The list is reloaded and shows the new key, masked...
    expect(await screen.findByText('abcdef12…')).toBeInTheDocument();
    // ...while the banner shows it in full, once, with a copy button.
    expect(screen.getByText('API key “CI key” created')).toBeInTheDocument();
    expect(screen.getByText(activeKey.key)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy key' })).toBeInTheDocument();
  });

  test('shows the API error when creating a key fails', async () => {
    setAuth({ isAdmin: false });
    routes['/auth/apikeys'] = () => respond([]);
    authAxios.post.mockImplementation(() => httpError(422, [{ loc: ['body', 'name'], msg: 'field required' }]));
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
    render(<ApiKeys />);

    await screen.findByText(/No API keys yet/);
    userEvent.type(screen.getByLabelText('Key Name'), 'x');
    userEvent.click(screen.getByRole('button', { name: 'Create API Key' }));
    expect(await screen.findByText('name: field required')).toBeInTheDocument();
    consoleError.mockRestore();
  });
});
