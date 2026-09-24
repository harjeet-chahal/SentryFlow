import React, { useCallback, useMemo, useRef, useState } from 'react';
import { useAuth } from '../components/auth/AuthContext';
import TimeRangePicker from '../components/TimeRangePicker';
import RateLimitRuleForm from '../components/RateLimitRuleForm';
import {
  PageHeader,
  PageSpinner,
  ErrorState,
  LiveIndicator,
  ChartCard,
  StatCard,
  EmptyChart,
  Badge,
} from '../components/ui';
import { AllowedVsRateLimitedChart, RateLimitedByEndpointChart } from '../components/AnalyticsWidgets';
import {
  DEFAULT_RANGE,
  LIVE_REFRESH_MS,
  rangeDescription,
  formatNumber,
  formatPercent,
  formatShare,
  formatDateTime,
  throttledUserRows,
} from '../utils/analytics';
import { algorithmLabel, endpointLabel, sortRules } from '../utils/limits';
import { getJson, apiErrorMessage } from '../utils/api';
import usePolling from '../utils/usePolling';

const th = 'px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider';
const td = 'px-3 py-4 whitespace-nowrap text-sm text-gray-500';
// The rules table is wide; its "Updated" column only shows on xl screens.
const xlOnly = 'hidden xl:table-cell';

// "all-endpoints" or the path, for messages like "the /api/v1/hello rule".
const ruleTarget = (endpoint) => (endpoint === '*' ? 'all-endpoints' : endpoint);

const AlgorithmBadge = ({ algorithm, title }) => (
  <Badge tone={algorithm === 'token_bucket' ? 'pink' : 'indigo'} title={title}>
    {algorithmLabel(algorithm)}
  </Badge>
);

const MostThrottledUsers = ({ rateLimits, rangeText }) => {
  const rows = useMemo(() => throttledUserRows(rateLimits), [rateLimits]);
  if (rows.length === 0) {
    return <EmptyChart message={`No users were rate limited in the ${rangeText}.`} />;
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th scope="col" className={th}>User</th>
            <th scope="col" className={`${th} text-right`}>Requests</th>
            <th scope="col" className={`${th} text-right`}>429s</th>
            <th scope="col" className={`${th} text-right`}>Share</th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {rows.map((row) => (
            <tr key={row.user_id}>
              <td className={`${td} font-medium text-gray-900`}>{row.username || row.user_id}</td>
              <td className={`${td} text-right tabular-nums`}>{formatNumber(row.requests)}</td>
              <td className={`${td} text-right tabular-nums text-gray-900`}>{formatNumber(row.rate_limited)}</td>
              <td className={`${td} text-right tabular-nums`}>{formatShare(row.rate_limited, row.requests)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const RulesTable = ({ rules, defaults, isAdmin, deletingId, onEdit, onDelete }) => (
  <div className="overflow-x-auto">
    <table className="min-w-full divide-y divide-gray-200">
      <thead className="bg-gray-50">
        <tr>
          <th scope="col" className={th}>Endpoint</th>
          {isAdmin && <th scope="col" className={th}>User</th>}
          <th scope="col" className={th}>Limit</th>
          <th scope="col" className={th}>Burst</th>
          <th scope="col" className={th}>Algorithm</th>
          <th scope="col" className={`${th} ${xlOnly}`}>Updated</th>
          {isAdmin && (
            <th scope="col" className={th}>
              <span className="sr-only">Actions</span>
            </th>
          )}
        </tr>
      </thead>
      <tbody className="bg-white divide-y divide-gray-200">
        {rules.map((rule) => (
          <tr key={rule.id}>
            <td className={`${td} font-medium text-gray-900`}>
              <code>{rule.endpoint}</code>
              {rule.endpoint === '*' && <div className="text-xs font-normal text-gray-500">{endpointLabel('*')}</div>}
            </td>
            {isAdmin && <td className={`${td} text-gray-900`}>{rule.username || rule.user_id}</td>}
            <td className={td}>{formatNumber(rule.requests_per_minute)} req/min</td>
            <td className={td}>{formatNumber(rule.burst_capacity)}</td>
            <td className={td}>
              <AlgorithmBadge algorithm={rule.algorithm} />
            </td>
            <td className={`${td} ${xlOnly}`}>{formatDateTime(rule.updated_at, 'MMM d, HH:mm')}</td>
            {isAdmin && (
              <td className={`${td} text-right space-x-3`}>
                <button
                  type="button"
                  onClick={() => onEdit(rule)}
                  className="font-medium text-blue-600 hover:text-blue-500"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(rule)}
                  disabled={deletingId === rule.id}
                  className="font-medium text-red-600 hover:text-red-500 disabled:text-gray-400"
                >
                  {deletingId === rule.id ? 'Deleting…' : 'Delete'}
                </button>
              </td>
            )}
          </tr>
        ))}
        {defaults && (
          <tr className="bg-gray-50">
            <td className={`${td} font-medium text-gray-900`}>
              <code>*</code>
              <div className="text-xs font-normal text-gray-500">Global default</div>
            </td>
            {isAdmin && <td className={td}>Everyone else</td>}
            <td className={td}>{formatNumber(defaults.requests_per_minute)} req/min</td>
            <td className={td}>{formatNumber(defaults.burst_capacity)}</td>
            <td className={td}>
              <AlgorithmBadge
                algorithm={defaults.algorithm}
                title={defaults.window_seconds ? `${defaults.window_seconds}-second window` : undefined}
              />
            </td>
            <td className={`${td} ${xlOnly}`}>—</td>
            {isAdmin && <td className={td} />}
          </tr>
        )}
      </tbody>
    </table>
  </div>
);

const RateLimitMonitor = () => {
  const { authAxios, isAdmin } = useAuth();
  const [range, setRange] = useState(DEFAULT_RANGE);
  const [editingRule, setEditingRule] = useState(null);
  const [formVersion, setFormVersion] = useState(0);
  const [notice, setNotice] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const formRef = useRef(null);

  const fetchRateLimits = useCallback(
    (signal) => getJson(authAxios, '/analytics/rate-limits', { params: { range }, signal }),
    [authAxios, range]
  );
  const analytics = usePolling(fetchRateLimits, { intervalMs: LIVE_REFRESH_MS });

  const fetchLimits = useCallback((signal) => getJson(authAxios, '/limits', { signal }), [authAxios]);
  const limits = usePolling(fetchLimits);

  // Admin-only: users for the rule form's picker.
  const fetchUsers = useCallback(
    (signal) => getJson(authAxios, '/analytics/users', { params: { range: '30d' }, signal }),
    [authAxios]
  );
  const users = usePolling(isAdmin ? fetchUsers : null);

  const rules = useMemo(() => sortRules(limits.data?.rules), [limits.data]);
  const defaults = limits.data?.defaults;
  const userList = users.data?.users;
  const rangeText = rangeDescription(range);
  const data = analytics.data;
  const totals = data?.totals ?? {};

  const nameFor = (rule) =>
    rule.username || userList?.find((u) => u.id === rule.user_id)?.username || rule.user_id;

  const handleEdit = (rule) => {
    setNotice(null);
    setActionError(null);
    setEditingRule(rule);
    formRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  };

  const handleCancelEdit = () => setEditingRule(null);

  const handleSaved = (rule) => {
    setActionError(null);
    setNotice(`Saved the ${ruleTarget(rule.endpoint)} rule for ${nameFor(rule)}. It takes effect immediately.`);
    setEditingRule(null);
    setFormVersion((v) => v + 1);
    limits.refresh();
  };

  const handleDelete = async (rule) => {
    const target = ruleTarget(rule.endpoint);
    const confirmed = window.confirm(
      `Delete the ${target} rule for ${nameFor(rule)}? Their requests fall back to the next matching rule or the global defaults.`
    );
    if (!confirmed) return;
    setDeletingId(rule.id);
    setNotice(null);
    setActionError(null);
    try {
      await authAxios.delete(`/limits/${rule.id}`);
      setNotice(`Deleted the ${target} rule for ${nameFor(rule)}.`);
      if (editingRule?.id === rule.id) setEditingRule(null);
      limits.refresh();
    } catch (err) {
      setActionError(apiErrorMessage(err));
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Rate Limit Monitor"
        subtitle={
          <>
            <span>{isAdmin ? 'All users' : 'Your API keys'}</span>
            <LiveIndicator
              lastUpdated={analytics.lastUpdated}
              error={data ? analytics.error : null}
              refreshing={analytics.refreshing}
            />
          </>
        }
      >
        <TimeRangePicker value={range} onChange={setRange} />
      </PageHeader>

      {analytics.loading && <PageSpinner />}

      {!data && analytics.error && <ErrorState error={analytics.error} autoRetry />}

      {data && (
        <div
          className={`space-y-6 transition-opacity ${analytics.isStale ? 'opacity-50' : ''}`}
          aria-busy={analytics.isStale}
        >
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <StatCard title="Requests" value={formatNumber(totals.requests)} caption={`In the ${rangeText}`} />
            <StatCard title="Rate limited" value={formatNumber(totals.rate_limited)} caption="Rejected with 429" />
            <StatCard
              title="Rate-limited share"
              value={formatPercent(totals.rate_limited_rate)}
              caption="Of all requests in this window"
            />
          </div>

          <ChartCard title="Allowed vs rate limited" subtitle="Requests per interval">
            {totals.requests ? (
              <AllowedVsRateLimitedChart rateLimits={data} />
            ) : (
              <EmptyChart message={`No requests in the ${rangeText}.`} />
            )}
          </ChartCard>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <ChartCard
              title="Rate limited by endpoint"
              subtitle="Endpoints with the most 429s"
              className={isAdmin ? '' : 'lg:col-span-2'}
            >
              <RateLimitedByEndpointChart rateLimits={data} rangeText={rangeText} />
            </ChartCard>
            {isAdmin && (
              <ChartCard title="Most throttled users" subtitle="Users with the most 429s">
                <MostThrottledUsers rateLimits={data} rangeText={rangeText} />
              </ChartCard>
            )}
          </div>
        </div>
      )}

      {/* Rate limit rules */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-4 py-5 sm:px-6">
          <h2 className="text-lg font-medium text-gray-900">Rate limit rules</h2>
          <p className="mt-1 text-sm text-gray-500">
            For each request the gateway uses the user's rule for that exact endpoint, then their <code>*</code> rule,
            then the global defaults.
          </p>
          {!isAdmin && (
            <p className="mt-2 text-sm text-gray-500">
              Limits are set by an administrator. These are the limits that apply to your API keys.
            </p>
          )}
        </div>

        {(notice || actionError) && (
          <div className="px-4 pb-4 sm:px-6">
            {notice && <div className="rounded-md bg-green-50 p-3 text-sm text-green-800">{notice}</div>}
            {actionError && (
              <div className="rounded-md bg-red-50 p-3 text-sm text-red-800" role="alert">
                {actionError}
              </div>
            )}
          </div>
        )}

        <div className="border-t border-gray-200">
          {limits.loading && <PageSpinner />}
          {!limits.data && limits.error && (
            <div className="p-4">
              <ErrorState error={limits.error} onRetry={limits.refresh} retrying={limits.refreshing} />
            </div>
          )}
          {limits.data && (
            <>
              <RulesTable
                rules={rules}
                defaults={defaults}
                isAdmin={isAdmin}
                deletingId={deletingId}
                onEdit={handleEdit}
                onDelete={handleDelete}
              />
              {rules.length === 0 && (
                <p className="px-6 py-4 text-sm text-gray-500 border-t border-gray-200">
                  {isAdmin
                    ? 'No custom rules yet, so every user gets the global defaults.'
                    : 'No custom rules apply to you, so the global defaults cover all of your requests.'}
                </p>
              )}
            </>
          )}
        </div>
      </div>

      {isAdmin && limits.data && (
        <div ref={formRef} className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900">
            {editingRule
              ? `Edit the ${ruleTarget(editingRule.endpoint)} rule for ${nameFor(editingRule)}`
              : 'Add or update a rule'}
          </h2>
          <p className="mt-1 mb-4 text-sm text-gray-500">
            Saving a rule for a user and endpoint that already has one replaces it. Changes apply immediately.
          </p>
          <RateLimitRuleForm
            key={`${editingRule?.id ?? 'new'}-${formVersion}`}
            rule={editingRule}
            defaults={defaults}
            users={userList}
            usersLoading={users.loading}
            usersError={users.error}
            onSaved={handleSaved}
            onCancel={handleCancelEdit}
          />
        </div>
      )}
    </div>
  );
};

export default RateLimitMonitor;
