import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../components/auth/AuthContext';
import TimeRangePicker from '../components/TimeRangePicker';
import { PageHeader, PageSpinner, ErrorState, ChartCard, Badge } from '../components/ui';
import { UsageSummaryCards, RequestsChart, LatencyChart } from '../components/AnalyticsWidgets';
import {
  DEFAULT_RANGE,
  rangeDescription,
  formatNumber,
  formatLatency,
  formatDateTime,
  formatRelative,
  epochToDate,
} from '../utils/analytics';
import { getJson } from '../utils/api';
import usePolling from '../utils/usePolling';

const th = 'px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider';
const td = 'px-6 py-4 whitespace-nowrap text-sm text-gray-500';
const pagerButton =
  'px-3 py-1 rounded-md bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:hover:bg-white';

// Users per page. The server ranks and pages, so this is all it sends.
export const USERS_PER_PAGE = 50;

// Non-admins never call the admin-only endpoints.
const AdminOnlyNotice = () => (
  <div className="space-y-6">
    <h1 className="text-2xl font-semibold text-gray-900">User View</h1>
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-lg font-medium text-gray-900">Only administrators can view per-user analytics</h2>
      <p className="mt-2 text-sm text-gray-600">
        Your own traffic is on the{' '}
        <Link to="/" className="font-medium text-blue-600 hover:text-blue-500">
          Dashboard
        </Link>
        , and every request your API keys made is in the{' '}
        <Link to="/logs" className="font-medium text-blue-600 hover:text-blue-500">
          Logs Explorer
        </Link>
        .
      </p>
    </div>
  </div>
);

// Traffic can outlive its account; the id is all that is left of it.
const displayName = (user) => user.username ?? user.id;

const LastSeen = ({ epochSeconds }) => {
  const date = epochToDate(epochSeconds);
  if (!date) return <span>Never</span>;
  return <span title={formatDateTime(date, 'MMM d, yyyy HH:mm:ss')}>{formatRelative(date)}</span>;
};

const UsersTable = ({ users, selectedId, onSelect }) => (
  <div className="overflow-x-auto max-h-96 overflow-y-auto">
    <table className="min-w-full divide-y divide-gray-200">
      <thead className="bg-gray-50 sticky top-0">
        <tr>
          <th scope="col" className={th}>User</th>
          <th scope="col" className={`${th} text-right`}>Requests</th>
          <th scope="col" className={`${th} text-right`}>Errors</th>
          <th scope="col" className={`${th} text-right`}>Rate limited</th>
          <th scope="col" className={`${th} text-right`}>p95</th>
          <th scope="col" className={th}>Last seen</th>
        </tr>
      </thead>
      <tbody className="bg-white divide-y divide-gray-200">
        {users.map((u) => {
          const selected = u.id === selectedId;
          return (
            <tr
              key={u.id}
              onClick={() => onSelect(u.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelect(u.id);
                }
              }}
              tabIndex={0}
              aria-selected={selected}
              className={`cursor-pointer focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500 ${
                selected ? 'bg-blue-50' : 'hover:bg-gray-50'
              }`}
            >
              <td className={td}>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{displayName(u)}</span>
                  {u.is_admin && <Badge tone="blue">Admin</Badge>}
                  {u.username === null ? (
                    <Badge tone="gray">Deleted</Badge>
                  ) : (
                    u.is_active === false && <Badge tone="gray">Inactive</Badge>
                  )}
                </div>
                {u.email && <div className="text-xs text-gray-500">{u.email}</div>}
              </td>
              <td className={`${td} text-right tabular-nums text-gray-900`}>{formatNumber(u.requests)}</td>
              <td className={`${td} text-right tabular-nums`}>{formatNumber(u.errors)}</td>
              <td className={`${td} text-right tabular-nums`}>{formatNumber(u.rate_limited)}</td>
              <td className={`${td} text-right tabular-nums`}>{formatLatency(u.p95_ms)}</td>
              <td className={td}>
                <LastSeen epochSeconds={u.last_seen} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  </div>
);

const Pager = ({ offset, count, total, onPrevious, onNext }) => (
  <div className="flex items-center justify-between px-6 py-3 border-t border-gray-200 text-sm text-gray-600">
    <span>
      {formatNumber(offset + 1)}–{formatNumber(offset + count)} of {formatNumber(total)}
    </span>
    <div className="flex gap-2">
      <button type="button" className={pagerButton} onClick={onPrevious} disabled={offset === 0}>
        Previous
      </button>
      <button type="button" className={pagerButton} onClick={onNext} disabled={offset + count >= total}>
        Next
      </button>
    </div>
  </div>
);

const SelectedUserUsage = ({ user, usage, rangeText }) => {
  const { data, error, loading, isStale, refresh, refreshing } = usage;
  if (loading) return <PageSpinner />;
  if (!data && error) return <ErrorState error={error} onRetry={refresh} retrying={refreshing} />;
  if (!data) return null;
  const summary = data.summary ?? {};
  return (
    <div className={`space-y-6 transition-opacity ${isStale ? 'opacity-50' : ''}`} aria-busy={isStale}>
      {!summary.requests ? (
        <div className="bg-white shadow rounded-lg p-6 text-sm text-gray-600">
          {displayName(user)} made no requests in the {rangeText}.
        </div>
      ) : (
        <>
          <UsageSummaryCards summary={summary} rangeText={rangeText} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <ChartCard title="Requests over time" subtitle="All requests, and those rejected with 429">
              <RequestsChart usage={data} />
            </ChartCard>
            <ChartCard title="Latency over time" subtitle="Served requests; gaps mean no served traffic">
              <LatencyChart usage={data} />
            </ChartCard>
          </div>
        </>
      )}
    </div>
  );
};

const AdminUserView = () => {
  const { authAxios } = useAuth();
  const [range, setRange] = useState(DEFAULT_RANGE);
  const [offset, setOffset] = useState(0);
  // Kept as a whole user, so the charts stay put while the table pages on.
  const [selectedUser, setSelectedUser] = useState(null);
  const selectedId = selectedUser?.id ?? null;

  const fetchUsers = useCallback(
    (signal) =>
      getJson(authAxios, '/analytics/users', { params: { range, limit: USERS_PER_PAGE, offset }, signal }),
    [authAxios, range, offset]
  );
  const usersQuery = usePolling(fetchUsers);
  const users = useMemo(() => usersQuery.data?.users ?? [], [usersQuery.data]);
  const total = usersQuery.data?.total ?? users.length;

  // Start with the busiest user selected.
  useEffect(() => {
    if (!selectedUser && users.length > 0) setSelectedUser(users[0]);
  }, [selectedUser, users]);

  const fetchUserUsage = useCallback(
    (signal) => getJson(authAxios, '/analytics/usage', { params: { range, user_id: selectedId }, signal }),
    [authAxios, range, selectedId]
  );
  const usage = usePolling(selectedId ? fetchUserUsage : null);

  // A new range ranks users afresh, so start again from the busiest.
  const changeRange = (next) => {
    setRange(next);
    setOffset(0);
  };
  const selectUser = (id) => setSelectedUser(users.find((u) => u.id === id) ?? null);
  const rangeText = rangeDescription(range);

  return (
    <div className="space-y-6">
      <PageHeader title="User View" subtitle={<span>Per-user traffic in the {rangeText}</span>}>
        <TimeRangePicker value={range} onChange={changeRange} />
      </PageHeader>

      {usersQuery.loading && <PageSpinner />}

      {!usersQuery.data && usersQuery.error && (
        <ErrorState error={usersQuery.error} onRetry={usersQuery.refresh} retrying={usersQuery.refreshing} />
      )}

      {usersQuery.data && (
        <div
          className={`bg-white shadow rounded-lg overflow-hidden transition-opacity ${usersQuery.isStale ? 'opacity-50' : ''}`}
        >
          <div className="px-4 py-5 sm:px-6">
            <h2 className="text-lg font-medium text-gray-900">Users</h2>
            <p className="mt-1 text-sm text-gray-500">Busiest first. Select a user to see their charts.</p>
          </div>
          {users.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-gray-500">No traffic in the {rangeText}.</p>
          ) : (
            <div className="border-t border-gray-200">
              <UsersTable users={users} selectedId={selectedId} onSelect={selectUser} />
              <Pager
                // The rows on screen, which lag the requested page while it loads.
                offset={usersQuery.data.offset ?? offset}
                count={users.length}
                total={total}
                onPrevious={() => setOffset(Math.max(0, offset - USERS_PER_PAGE))}
                onNext={() => setOffset(offset + USERS_PER_PAGE)}
              />
            </div>
          )}
        </div>
      )}

      {selectedUser && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold text-gray-900">
            {displayName(selectedUser)}
            <span className="ml-2 text-sm font-normal text-gray-500">in the {rangeText}</span>
          </h2>
          <SelectedUserUsage user={selectedUser} usage={usage} rangeText={rangeText} />
        </div>
      )}
    </div>
  );
};

const UserView = () => {
  const { isAdmin } = useAuth();
  return isAdmin ? <AdminUserView /> : <AdminOnlyNotice />;
};

export default UserView;
