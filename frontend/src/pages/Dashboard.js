import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../components/auth/AuthContext';
import GatewayCurlExample from '../components/GatewayCurlExample';
import TimeRangePicker from '../components/TimeRangePicker';
import { PageHeader, PageSpinner, ErrorState, LiveIndicator, ChartCard } from '../components/ui';
import {
  UsageSummaryCards,
  RequestsChart,
  LatencyChart,
  StatusCodeChart,
  TopEndpointsChart,
} from '../components/AnalyticsWidgets';
import { DEFAULT_RANGE, LIVE_REFRESH_MS, rangeDescription } from '../utils/analytics';
import { getJson } from '../utils/api';
import usePolling from '../utils/usePolling';

// Shown when the selected window has no traffic at all.
const NoTrafficYet = ({ rangeText, isAdmin }) => (
  <div className="bg-white shadow rounded-lg p-6">
    <h2 className="text-lg font-medium text-gray-900">No traffic in the {rangeText} yet</h2>
    <p className="mt-1 text-sm text-gray-600">
      {isAdmin
        ? 'No user has sent requests through the gateway in this window.'
        : "Your API keys haven't sent any requests through the gateway in this window."}{' '}
      Charts show up here as soon as requests arrive; this page refreshes every 10 seconds.
    </p>
    <ol className="mt-4 space-y-3 text-sm text-gray-700 list-decimal list-inside">
      <li>
        Create an API key on the{' '}
        <Link to="/api-keys" className="font-medium text-blue-600 hover:text-blue-500">
          API Keys
        </Link>{' '}
        page.
      </li>
      <li>
        Trade it for a token and send a request through the gateway:
        <GatewayCurlExample apiKey="<key>" className="mt-2" />
      </li>
    </ol>
    <p className="mt-4 text-sm text-gray-500">Already sent some? Try a longer time range.</p>
  </div>
);

const Dashboard = () => {
  const { authAxios, isAdmin } = useAuth();
  const [range, setRange] = useState(DEFAULT_RANGE);

  const fetchUsage = useCallback(
    (signal) => getJson(authAxios, '/analytics/usage', { params: { range }, signal }),
    [authAxios, range]
  );
  const { data, error, loading, refreshing, isStale, lastUpdated } = usePolling(fetchUsage, {
    intervalMs: LIVE_REFRESH_MS,
  });

  const rangeText = rangeDescription(range);
  const summary = data?.summary ?? {};

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard Overview"
        subtitle={
          <>
            <span>{isAdmin ? 'All users' : 'Your API keys'}</span>
            <LiveIndicator lastUpdated={lastUpdated} error={data ? error : null} refreshing={refreshing} />
          </>
        }
      >
        <TimeRangePicker value={range} onChange={setRange} />
      </PageHeader>

      {loading && <PageSpinner />}

      {!data && error && <ErrorState error={error} autoRetry />}

      {data && (
        <div className={`space-y-6 transition-opacity ${isStale ? 'opacity-50' : ''}`} aria-busy={isStale}>
          {!summary.requests ? (
            <NoTrafficYet rangeText={rangeText} isAdmin={isAdmin} />
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

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <ChartCard title="Status code distribution" subtitle="429s count as 4xx">
                  <StatusCodeChart statusCodes={data.status_codes} />
                </ChartCard>
                <ChartCard title="Top endpoints" subtitle="By request count">
                  <TopEndpointsChart usage={data} />
                </ChartCard>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default Dashboard;
