// Cards and charts that render analytics API responses. Shared by the
// Dashboard, User View and Rate Limit Monitor pages.
import React, { useMemo } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Line, Bar, Pie } from 'react-chartjs-2';
import { StatCard, EmptyChart } from './ui';
import {
  buildRequestsChartData,
  buildLatencyChartData,
  buildStatusCodeChartData,
  buildTopEndpointsChartData,
  buildAllowedVsRateLimitedChartData,
  buildRateLimitedByEndpointChartData,
  countLineOptions,
  latencyLineOptions,
  endpointBarOptions,
  statusCodePieOptions,
  statusCodeBreakdown,
  topEndpointRows,
  topEndpointTooltipLines,
  throttledEndpointRows,
  throttledEndpointTooltipLabel,
  hasLatencyData,
  formatNumber,
  formatLatency,
  formatPercent,
} from '../utils/analytics';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Tooltip,
  Legend,
  Filler
);

const REQUEST_LINE_OPTIONS = countLineOptions('Requests');
const LATENCY_LINE_OPTIONS = latencyLineOptions();
const STATUS_PIE_OPTIONS = statusCodePieOptions();

// The four headline numbers from /analytics/usage `summary`.
export const UsageSummaryCards = ({ summary = {}, rangeText }) => (
  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
    <StatCard title="Total requests" value={formatNumber(summary.requests)} caption={`In the ${rangeText}`} />
    <StatCard
      title="Latency"
      value={
        <>
          {formatLatency(summary.p95_ms)} <span className="text-base font-medium text-gray-500">p95</span>
        </>
      }
      detail={`avg ${formatLatency(summary.avg_ms)} · p99 ${formatLatency(summary.p99_ms)}`}
      caption="Served requests only (429s excluded)"
    />
    <StatCard
      title="Error rate"
      value={formatPercent(summary.error_rate)}
      detail={`${formatNumber(summary.errors)} errors`}
      caption="4xx/5xx, excluding 429"
    />
    <StatCard
      title="Rate limited"
      value={formatNumber(summary.rate_limited)}
      detail={`${formatPercent(summary.rate_limited_rate)} of requests`}
      caption="429 responses"
    />
  </div>
);

export const RequestsChart = ({ usage }) => {
  const data = useMemo(() => buildRequestsChartData(usage), [usage]);
  return (
    <div className="relative h-72">
      <Line data={data} options={REQUEST_LINE_OPTIONS} aria-label="Requests over time" />
    </div>
  );
};

export const LatencyChart = ({ usage }) => {
  const data = useMemo(() => buildLatencyChartData(usage), [usage]);
  if (!hasLatencyData(usage)) {
    return <EmptyChart message="No served requests in this window, so there is no latency to show." />;
  }
  return (
    <div className="relative h-72">
      <Line data={data} options={LATENCY_LINE_OPTIONS} aria-label="Latency over time" />
    </div>
  );
};

// Pie plus a small table with the same numbers, so nothing is hover-only.
export const StatusCodeChart = ({ statusCodes }) => {
  const breakdown = useMemo(() => statusCodeBreakdown(statusCodes), [statusCodes]);
  const data = useMemo(() => buildStatusCodeChartData(statusCodes), [statusCodes]);
  if (breakdown.total === 0) {
    return <EmptyChart message="No responses in this window." heightClass="h-56" />;
  }
  // Side by side only where the card is wide enough (it is half-width at lg).
  return (
    <div className="flex flex-col items-center gap-6 sm:flex-row lg:flex-col xl:flex-row">
      <div className="relative h-48 w-48 flex-shrink-0">
        <Pie data={data} options={STATUS_PIE_OPTIONS} aria-label="Status code distribution" />
      </div>
      <table className="w-full text-sm">
        <caption className="sr-only">Responses by status class</caption>
        <tbody>
          {breakdown.rows.map((row) => (
            <tr key={row.cls}>
              <th scope="row" className="whitespace-nowrap py-1 text-left font-medium text-gray-700">
                <span
                  className="mr-2 inline-block h-3 w-3 rounded-sm align-middle"
                  style={{ backgroundColor: row.color }}
                  aria-hidden="true"
                />
                {row.cls}
              </th>
              <td className="whitespace-nowrap py-1 text-right tabular-nums text-gray-900">{formatNumber(row.count)}</td>
              <td className="w-20 whitespace-nowrap py-1 pl-3 text-right tabular-nums text-gray-500">
                {formatPercent(row.share)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export const TopEndpointsChart = ({ usage }) => {
  const rows = useMemo(() => topEndpointRows(usage), [usage]);
  const data = useMemo(() => buildTopEndpointsChartData(usage), [usage]);
  const options = useMemo(() => endpointBarOptions(rows, { afterLabel: topEndpointTooltipLines }), [rows]);
  if (rows.length === 0) return <EmptyChart message="No endpoint traffic in this window." />;
  return (
    <div className="relative h-72">
      <Bar data={data} options={options} aria-label="Top endpoints by requests" />
    </div>
  );
};

export const AllowedVsRateLimitedChart = ({ rateLimits }) => {
  const data = useMemo(() => buildAllowedVsRateLimitedChartData(rateLimits), [rateLimits]);
  return (
    <div className="relative h-72">
      <Line data={data} options={REQUEST_LINE_OPTIONS} aria-label="Allowed and rate-limited requests over time" />
    </div>
  );
};

export const RateLimitedByEndpointChart = ({ rateLimits, rangeText }) => {
  const rows = useMemo(() => throttledEndpointRows(rateLimits), [rateLimits]);
  const data = useMemo(() => buildRateLimitedByEndpointChartData(rateLimits), [rateLimits]);
  const options = useMemo(() => endpointBarOptions(rows, { label: throttledEndpointTooltipLabel }), [rows]);
  if (rows.length === 0) {
    return <EmptyChart message={`No requests were rate limited in the ${rangeText}.`} />;
  }
  return (
    <div className="relative h-72">
      <Bar data={data} options={options} aria-label="Rate-limited requests by endpoint" />
    </div>
  );
};
