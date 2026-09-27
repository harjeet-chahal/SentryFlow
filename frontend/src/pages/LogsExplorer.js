import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowPathIcon } from '@heroicons/react/24/outline';
import { useAuth } from '../components/auth/AuthContext';
import TimeRangePicker from '../components/TimeRangePicker';
import { PageHeader, PageSpinner, ErrorState } from '../components/ui';
import { formatDateTime, formatNumber, rangeDescription } from '../utils/analytics';
import { getJson } from '../utils/api';
import usePolling from '../utils/usePolling';

const LOGS_PER_PAGE = 25;
const ROW_LIMITS = [100, 200, 500, 1000];

const selectClass = 'form-input sm:text-sm disabled:bg-gray-100 disabled:text-gray-500';
const th = 'px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider';

// Returns `value` once it has stopped changing for `delayMs`.
const useDebouncedValue = (value, delayMs) => {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
};

const getStatusCodeClass = (statusCode) => {
  if (statusCode === 429) return 'bg-orange-100 text-orange-800';
  switch (Math.floor(statusCode / 100)) {
    case 2:
      return 'bg-green-100 text-green-800';
    case 3:
      return 'bg-blue-100 text-blue-800';
    case 4:
      return 'bg-yellow-100 text-yellow-800';
    case 5:
      return 'bg-red-100 text-red-800';
    default:
      return 'bg-gray-100 text-gray-800';
  }
};

// Lets long paths wrap at "/" rather than in the middle of a segment.
const BreakablePath = ({ path }) =>
  String(path ?? '')
    .split('/')
    .map((segment, i) => (
      <React.Fragment key={i}>
        {i > 0 && <wbr />}
        {i > 0 ? `/${segment}` : segment}
      </React.Fragment>
    ));

const getResponseTimeClass = (ms) => {
  if (ms >= 500) return 'text-red-600';
  if (ms >= 300) return 'text-yellow-600';
  return 'text-gray-900';
};

const LogsExplorer = () => {
  const { authAxios, isAdmin } = useAuth();
  const [range, setRange] = useState('1h');
  const [statusFilter, setStatusFilter] = useState('all'); // all, 2xx, 3xx, 4xx, 5xx
  const [endpointInput, setEndpointInput] = useState('');
  const [userId, setUserId] = useState('');
  const [limit, setLimit] = useState(200);
  const [page, setPage] = useState(1);
  const endpointFilter = useDebouncedValue(endpointInput.trim(), 300);

  // Filtering happens on the server.
  const fetchLogs = useCallback(
    (signal) => {
      const params = { range, status: statusFilter, limit };
      if (endpointFilter) params.endpoint = endpointFilter;
      if (isAdmin && userId) params.user_id = userId;
      return getJson(authAxios, '/analytics/logs', { params, signal });
    },
    [authAxios, range, statusFilter, endpointFilter, userId, limit, isAdmin]
  );
  const { data, error, loading, refreshing, isStale, refresh } = usePolling(fetchLogs);

  // Admins can narrow the logs to one user.
  const fetchUsers = useCallback(
    (signal) => getJson(authAxios, '/analytics/users', { params: { range: '30d' }, signal }),
    [authAxios]
  );
  const users = usePolling(isAdmin ? fetchUsers : null);
  const userOptions = useMemo(
    () => [...(users.data?.users ?? [])].sort((a, b) => String(a.username).localeCompare(String(b.username))),
    [users.data]
  );

  const rows = useMemo(() => (Array.isArray(data?.rows) ? data.rows : []), [data]);
  const totalPages = Math.max(1, Math.ceil(rows.length / LOGS_PER_PAGE));
  const currentPage = Math.min(page, totalPages);
  const startIndex = (currentPage - 1) * LOGS_PER_PAGE;
  const pageRows = rows.slice(startIndex, startIndex + LOGS_PER_PAGE);

  // Every new result set starts on the first page.
  useEffect(() => {
    setPage(1);
  }, [data]);

  const resultSummary = data
    ? data.truncated
      ? `Showing the latest ${formatNumber(rows.length)} matching requests`
      : `${formatNumber(rows.length)} matching ${rows.length === 1 ? 'request' : 'requests'}`
    : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Logs Explorer"
        subtitle={resultSummary && <span>{`${resultSummary} in the ${rangeDescription(data.range ?? range)}`}</span>}
      >
        <button
          type="button"
          onClick={refresh}
          disabled={refreshing}
          className="inline-flex items-center px-3 py-1 text-sm rounded-md bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          <ArrowPathIcon className={`mr-1 h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} aria-hidden="true" />
          Refresh
        </button>
        <TimeRangePicker value={range} onChange={setRange} />
      </PageHeader>

      {/* Filters */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Filters</h2>

        <div className={`grid grid-cols-1 gap-4 ${isAdmin ? 'md:grid-cols-4' : 'md:grid-cols-3'}`}>
          <div>
            <label htmlFor="status-filter" className="block text-sm font-medium text-gray-700 mb-1">
              Status Code
            </label>
            <select
              id="status-filter"
              className={selectClass}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All</option>
              <option value="2xx">2xx (Success)</option>
              <option value="3xx">3xx (Redirection)</option>
              <option value="4xx">4xx (Client Error, incl. 429)</option>
              <option value="5xx">5xx (Server Error)</option>
            </select>
          </div>

          <div>
            <label htmlFor="endpoint-filter" className="block text-sm font-medium text-gray-700 mb-1">
              Endpoint
            </label>
            <input
              type="text"
              id="endpoint-filter"
              className={selectClass}
              placeholder="e.g. /api/v1/hello"
              value={endpointInput}
              onChange={(e) => setEndpointInput(e.target.value)}
            />
          </div>

          {isAdmin && (
            <div>
              <label htmlFor="user-filter" className="block text-sm font-medium text-gray-700 mb-1">
                User
              </label>
              <select
                id="user-filter"
                className={selectClass}
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                disabled={Boolean(users.error)}
              >
                <option value="">{users.error ? 'User list unavailable' : 'All users'}</option>
                {userOptions.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label htmlFor="limit-filter" className="block text-sm font-medium text-gray-700 mb-1">
              Rows
            </label>
            <select
              id="limit-filter"
              className={selectClass}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              {ROW_LIMITS.map((n) => (
                <option key={n} value={n}>
                  Latest {n}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Logs table */}
      {loading && <PageSpinner />}

      {!data && error && <ErrorState error={error} onRetry={refresh} retrying={refreshing} />}

      {data && (
        <div
          className={`bg-white shadow rounded-lg overflow-hidden transition-opacity ${isStale ? 'opacity-50' : ''}`}
          aria-busy={isStale}
        >
          {error && (
            <div className="px-4 py-3 text-sm text-amber-800 bg-amber-50 border-b border-amber-100" role="status">
              Couldn't refresh the logs; showing the previous results.
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className={th}>
                    Timestamp
                  </th>
                  {isAdmin && (
                    <th scope="col" className={th}>
                      User
                    </th>
                  )}
                  <th scope="col" className={th}>
                    Endpoint
                  </th>
                  <th scope="col" className={th}>
                    Status
                  </th>
                  <th scope="col" className={th}>
                    Response Time
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {pageRows.map((log, i) => (
                  <tr key={`${log.timestamp}-${startIndex + i}`} className="hover:bg-gray-50">
                    <td
                      className="px-4 py-4 whitespace-nowrap text-sm text-gray-500"
                      title={formatDateTime(log.timestamp, 'yyyy-MM-dd HH:mm:ss')}
                    >
                      {formatDateTime(log.timestamp, 'MMM d, HH:mm:ss')}
                    </td>
                    {isAdmin && (
                      <td className="px-4 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        {log.username || log.user_id}
                      </td>
                    )}
                    <td className="px-4 py-4 text-sm text-gray-500 font-mono">
                      <BreakablePath path={log.endpoint} />
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusCodeClass(log.status_code)}`}
                        title={log.status_code === 429 ? 'Rejected by the rate limiter' : undefined}
                      >
                        {log.status_code}
                      </span>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap text-sm font-medium">
                      {/* Gateway time. For a 429 that is the key lookup and limit check. */}
                      <span className={getResponseTimeClass(log.response_time_ms)}>
                        {formatNumber(log.response_time_ms)} ms
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {rows.length === 0 && (
            <p className="px-6 py-8 text-center text-sm text-gray-500">
              No requests match these filters in the {rangeDescription(data.range ?? range)}.
            </p>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200 sm:px-6">
              <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm text-gray-700">
                    Showing <span className="font-medium">{startIndex + 1}</span> to{' '}
                    <span className="font-medium">{Math.min(startIndex + LOGS_PER_PAGE, rows.length)}</span> of{' '}
                    <span className="font-medium">{rows.length}</span> results
                  </p>
                </div>
                <div>
                  <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px" aria-label="Pagination">
                    <button
                      onClick={() => setPage(currentPage - 1)}
                      disabled={currentPage === 1}
                      className={`relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 bg-white text-sm font-medium ${currentPage === 1 ? 'text-gray-300 cursor-not-allowed' : 'text-gray-500 hover:bg-gray-50'}`}
                    >
                      Previous
                    </button>

                    {/* Page numbers */}
                    {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                      let pageNum;
                      if (totalPages <= 5) {
                        pageNum = i + 1;
                      } else if (currentPage <= 3) {
                        pageNum = i + 1;
                      } else if (currentPage >= totalPages - 2) {
                        pageNum = totalPages - 4 + i;
                      } else {
                        pageNum = currentPage - 2 + i;
                      }

                      return (
                        <button
                          key={pageNum}
                          onClick={() => setPage(pageNum)}
                          aria-current={currentPage === pageNum ? 'page' : undefined}
                          className={`relative inline-flex items-center px-4 py-2 border border-gray-300 bg-white text-sm font-medium ${currentPage === pageNum ? 'z-10 bg-blue-50 border-blue-500 text-blue-600' : 'text-gray-500 hover:bg-gray-50'}`}
                        >
                          {pageNum}
                        </button>
                      );
                    })}

                    <button
                      onClick={() => setPage(currentPage + 1)}
                      disabled={currentPage === totalPages}
                      className={`relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 bg-white text-sm font-medium ${currentPage === totalPages ? 'text-gray-300 cursor-not-allowed' : 'text-gray-500 hover:bg-gray-50'}`}
                    >
                      Next
                    </button>
                  </nav>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default LogsExplorer;
