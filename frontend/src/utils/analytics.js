// Pure helpers for the analytics API: time ranges, formatters, and builders
// that turn API responses into chart.js `data` / `options` objects.
// No React in here, so everything is unit-testable.
import { format, formatDistanceStrict } from 'date-fns';

// ---------------------------------------------------------------------------
// Time ranges
// ---------------------------------------------------------------------------

export const TIME_RANGES = [
  { value: '1h', label: '1h', description: 'last hour', stepSeconds: 60 },
  { value: '24h', label: '24h', description: 'last 24 hours', stepSeconds: 3600 },
  { value: '7d', label: '7d', description: 'last 7 days', stepSeconds: 21600 },
  { value: '30d', label: '30d', description: 'last 30 days', stepSeconds: 86400 },
];

export const DEFAULT_RANGE = '24h';

// How often the live views (Dashboard, Rate Limit Monitor) re-fetch.
export const LIVE_REFRESH_MS = 10000;

const DAY_SECONDS = 86400;
const SIX_HOURS_SECONDS = 21600;

export function rangeDescription(range) {
  const match = TIME_RANGES.find((r) => r.value === range);
  return match ? match.description : range;
}

// ---------------------------------------------------------------------------
// Formatters (null / undefined / NaN render as an em dash)
// ---------------------------------------------------------------------------

export const EMPTY_VALUE = '—';

const isMissing = (value) =>
  value === null || value === undefined || value === '' || !Number.isFinite(Number(value));

export function formatNumber(value) {
  if (isMissing(value)) return EMPTY_VALUE;
  return Number(value).toLocaleString();
}

export function formatLatency(ms) {
  if (isMissing(ms)) return EMPTY_VALUE;
  const n = Number(ms);
  const rounded = n >= 100 ? Math.round(n) : Math.round(n * 10) / 10;
  return `${rounded.toLocaleString()} ms`;
}

// `value` is already a percentage (0-100), as the API returns it.
export function formatPercent(value) {
  if (isMissing(value)) return EMPTY_VALUE;
  const n = Number(value);
  if (n > 0 && n < 0.01) return '<0.01%';
  const rounded = n >= 10 ? n.toFixed(1) : n.toFixed(2);
  return `${parseFloat(rounded)}%`;
}

export function formatShare(count, total) {
  if (isMissing(count) || isMissing(total) || Number(total) <= 0) return EMPTY_VALUE;
  return formatPercent((Number(count) / Number(total)) * 100);
}

// Chart x-axis label for a series bucket. `epochSeconds` is the bucket start
// (UTC). Day buckets are UTC days, so they are labelled with the UTC date;
// shorter buckets are labelled in the viewer's local time.
export function formatBucketLabel(epochSeconds, stepSeconds) {
  if (isMissing(epochSeconds)) return '';
  const date = new Date(Number(epochSeconds) * 1000);
  const step = Number(stepSeconds) || 0;
  if (step >= DAY_SECONDS) {
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
  }
  if (step >= SIX_HOURS_SECONDS) return format(date, 'MMM d HH:mm');
  return format(date, 'HH:mm');
}

// Parses an API timestamp. The backend stores naive UTC datetimes, so an ISO
// string without an offset is treated as UTC rather than local time.
export function parseApiDate(value) {
  if (value === null || value === undefined || value === '') return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  let text = String(value).trim();
  // Python emits microseconds; keep milliseconds for older JS engines.
  text = text.replace(/(\.\d{3})\d+/, '$1');
  if (/^\d{4}-\d{2}-\d{2}T[\d:.]+$/.test(text)) text = `${text}Z`;
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function epochToDate(epochSeconds) {
  if (isMissing(epochSeconds)) return null;
  return new Date(Number(epochSeconds) * 1000);
}

export function formatDateTime(value, pattern = 'MMM d, yyyy HH:mm') {
  const date = value instanceof Date ? value : parseApiDate(value);
  return date ? format(date, pattern) : EMPTY_VALUE;
}

export function formatRelative(date, now = new Date()) {
  if (!date) return EMPTY_VALUE;
  if (Math.abs(now.getTime() - date.getTime()) < 60000) return 'just now';
  return formatDistanceStrict(date, now, { addSuffix: true });
}

export function maskKey(key, visible = 8) {
  if (!key) return '';
  return key.length <= visible ? key : `${key.slice(0, visible)}…`;
}

// Endpoint paths share their prefix (/api/v1/...), so keep the end, cut at
// a segment boundary when there is one.
export function truncatePath(path, max = 22) {
  const text = String(path ?? '');
  if (text.length <= max) return text;
  let tail = text.slice(text.length - (max - 1));
  const slash = tail.indexOf('/');
  if (slash > 0) tail = tail.slice(slash);
  return `…${tail}`;
}

// ---------------------------------------------------------------------------
// Chart colours (validated for colour-blind separation as pairs/sets)
// ---------------------------------------------------------------------------

export const COLORS = {
  requests: '#2563eb', // blue-600: served / allowed traffic
  rateLimited: '#ea580c', // orange-600: 429s
  latencyP95: '#2563eb',
  latencyAvg: '#0d9488', // teal-600
  status: {
    '2xx': '#2563eb',
    '3xx': '#94a3b8', // neutral
    '4xx': '#f59e0b',
    '5xx': '#b91c1c',
  },
};

export function withAlpha(hex, alpha) {
  const clean = hex.replace('#', '');
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// ---------------------------------------------------------------------------
// Response helpers
// ---------------------------------------------------------------------------

const toCount = (value) => (isMissing(value) ? 0 : Number(value));
const toNullableNumber = (value) => (isMissing(value) ? null : Number(value));

export function seriesOf(response) {
  return Array.isArray(response?.series) ? response.series : [];
}

export function stepSecondsOf(response) {
  const step = Number(response?.step_seconds);
  if (Number.isFinite(step) && step > 0) return step;
  const range = TIME_RANGES.find((r) => r.value === response?.range);
  if (range) return range.stepSeconds;
  const series = seriesOf(response);
  if (series.length > 1) return Number(series[1].t) - Number(series[0].t);
  return 3600;
}

export function bucketLabels(response) {
  const step = stepSecondsOf(response);
  return seriesOf(response).map((point) => formatBucketLabel(point.t, step));
}

export function hasLatencyData(usage) {
  return seriesOf(usage).some((p) => !isMissing(p.p95_ms) || !isMissing(p.avg_ms));
}

// chart.js hides points on lines (radius 0), which would make a lone value
// between two gaps invisible. Show a dot only for such isolated values.
export function isolatedPointRadius(context) {
  const values = context?.dataset?.data;
  const index = context?.dataIndex;
  if (!Array.isArray(values) || typeof index !== 'number') return 0;
  const present = (i) => i >= 0 && i < values.length && values[i] !== null && values[i] !== undefined;
  if (!present(index)) return 0;
  return !present(index - 1) && !present(index + 1) ? 3 : 0;
}

const LINE_STYLE = {
  borderWidth: 2,
  pointRadius: 0,
  pointHoverRadius: 4,
  pointHitRadius: 8,
  tension: 0.25,
};

// ---------------------------------------------------------------------------
// Chart data builders
// ---------------------------------------------------------------------------

// /analytics/usage: requests and 429s per bucket.
export function buildRequestsChartData(usage) {
  const series = seriesOf(usage);
  return {
    labels: bucketLabels(usage),
    datasets: [
      {
        ...LINE_STYLE,
        label: 'Requests',
        data: series.map((p) => toCount(p.requests)),
        borderColor: COLORS.requests,
        backgroundColor: withAlpha(COLORS.requests, 0.08),
        fill: true,
      },
      {
        ...LINE_STYLE,
        label: 'Rate limited (429)',
        data: series.map((p) => toCount(p.rate_limited)),
        borderColor: COLORS.rateLimited,
        backgroundColor: COLORS.rateLimited,
        fill: false,
      },
    ],
  };
}

// /analytics/usage: p95 and average latency. Buckets without served requests
// are null and render as gaps.
export function buildLatencyChartData(usage) {
  const series = seriesOf(usage);
  const latencyLine = {
    ...LINE_STYLE,
    fill: false,
    spanGaps: false,
    pointRadius: isolatedPointRadius,
  };
  return {
    labels: bucketLabels(usage),
    datasets: [
      {
        ...latencyLine,
        label: 'p95',
        data: series.map((p) => toNullableNumber(p.p95_ms)),
        borderColor: COLORS.latencyP95,
        backgroundColor: COLORS.latencyP95,
      },
      {
        ...latencyLine,
        label: 'Average',
        data: series.map((p) => toNullableNumber(p.avg_ms)),
        borderColor: COLORS.latencyAvg,
        backgroundColor: COLORS.latencyAvg,
      },
    ],
  };
}

export const STATUS_CLASSES = ['2xx', '3xx', '4xx', '5xx'];

// Rows for the status-code legend/table: count and share of each class.
export function statusCodeBreakdown(statusCodes) {
  const counts = STATUS_CLASSES.map((cls) => ({ cls, count: toCount(statusCodes?.[cls]) }));
  const total = counts.reduce((sum, row) => sum + row.count, 0);
  return {
    total,
    rows: counts.map((row) => ({
      ...row,
      color: COLORS.status[row.cls],
      share: total > 0 ? (row.count / total) * 100 : 0,
    })),
  };
}

export function buildStatusCodeChartData(statusCodes) {
  const { rows } = statusCodeBreakdown(statusCodes);
  return {
    labels: rows.map((row) => row.cls),
    datasets: [
      {
        label: 'Responses',
        data: rows.map((row) => row.count),
        backgroundColor: rows.map((row) => row.color),
        borderColor: '#ffffff',
        borderWidth: 2,
      },
    ],
  };
}

// Tooltip line for the status-code pie: "4xx: 120 (9.7%)".
export function statusCodeTooltipLabel(context) {
  const values = context?.dataset?.data ?? [];
  const total = values.reduce((sum, v) => sum + toCount(v), 0);
  const value = toCount(context?.raw);
  return `${context?.label ?? ''}: ${formatNumber(value)} (${formatShare(value, total)})`;
}

export function topEndpointRows(usage, limit = 8) {
  const rows = Array.isArray(usage?.top_endpoints) ? usage.top_endpoints : [];
  return rows.slice(0, limit);
}

export function buildTopEndpointsChartData(usage, limit = 8) {
  const rows = topEndpointRows(usage, limit);
  return {
    labels: rows.map((row) => row.endpoint),
    datasets: [
      {
        label: 'Requests',
        data: rows.map((row) => toCount(row.requests)),
        backgroundColor: COLORS.requests,
        borderRadius: 4,
        maxBarThickness: 22,
      },
    ],
  };
}

export function topEndpointTooltipLines(row) {
  if (!row) return [];
  return [
    `Errors: ${formatNumber(toCount(row.errors))}`,
    `Rate limited: ${formatNumber(toCount(row.rate_limited))}`,
    `p95: ${formatLatency(row.p95_ms)}`,
  ];
}

// /analytics/rate-limits: allowed vs 429 per bucket.
export function buildAllowedVsRateLimitedChartData(rateLimits) {
  const series = seriesOf(rateLimits);
  return {
    labels: bucketLabels(rateLimits),
    datasets: [
      {
        ...LINE_STYLE,
        label: 'Allowed',
        data: series.map((p) => toCount(p.allowed)),
        borderColor: COLORS.requests,
        backgroundColor: withAlpha(COLORS.requests, 0.08),
        fill: true,
      },
      {
        ...LINE_STYLE,
        label: 'Rate limited (429)',
        data: series.map((p) => toCount(p.rate_limited)),
        borderColor: COLORS.rateLimited,
        backgroundColor: withAlpha(COLORS.rateLimited, 0.12),
        fill: true,
      },
    ],
  };
}

// Endpoints that were actually throttled, most-throttled first.
export function throttledEndpointRows(rateLimits, limit = 10) {
  const rows = Array.isArray(rateLimits?.by_endpoint) ? rateLimits.by_endpoint : [];
  return rows
    .filter((row) => toCount(row.rate_limited) > 0)
    .sort((a, b) => toCount(b.rate_limited) - toCount(a.rate_limited))
    .slice(0, limit);
}

export function buildRateLimitedByEndpointChartData(rateLimits, limit = 10) {
  const rows = throttledEndpointRows(rateLimits, limit);
  return {
    labels: rows.map((row) => row.endpoint),
    datasets: [
      {
        label: 'Rate limited (429)',
        data: rows.map((row) => toCount(row.rate_limited)),
        backgroundColor: COLORS.rateLimited,
        borderRadius: 4,
        maxBarThickness: 22,
      },
    ],
  };
}

export function throttledEndpointTooltipLabel(row) {
  if (!row) return '';
  const limited = toCount(row.rate_limited);
  const total = toCount(row.requests);
  return `${formatNumber(limited)} of ${formatNumber(total)} requests (${formatShare(limited, total)})`;
}

// Users with at least one 429, most-throttled first.
export function throttledUserRows(rateLimits, limit = 10) {
  const rows = Array.isArray(rateLimits?.by_user) ? rateLimits.by_user : [];
  return rows
    .filter((row) => toCount(row.rate_limited) > 0)
    .sort((a, b) => toCount(b.rate_limited) - toCount(a.rate_limited))
    .slice(0, limit);
}

// ---------------------------------------------------------------------------
// Chart options
// ---------------------------------------------------------------------------

// Tooltip rows keyed by a short stroke in the series colour.
const lineTooltipColor = (context) => ({
  borderColor: context.dataset.borderColor,
  backgroundColor: context.dataset.borderColor,
});

function lineOptions({ yTitle, formatValue, integerTicks }) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        position: 'top',
        align: 'end',
        labels: { usePointStyle: true, pointStyle: 'line', boxWidth: 24 },
      },
      tooltip: {
        boxWidth: 12,
        boxHeight: 2,
        callbacks: {
          labelColor: lineTooltipColor,
          label: (context) => `${context.dataset.label}: ${formatValue(context.raw)}`,
        },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { maxRotation: 0, autoSkipPadding: 16 },
      },
      y: {
        beginAtZero: true,
        title: { display: Boolean(yTitle), text: yTitle },
        ticks: integerTicks ? { precision: 0 } : {},
      },
    },
  };
}

export function countLineOptions(yTitle = 'Requests') {
  return lineOptions({ yTitle, formatValue: formatNumber, integerTicks: true });
}

export function latencyLineOptions() {
  return lineOptions({ yTitle: 'Latency (ms)', formatValue: formatLatency, integerTicks: false });
}

// Horizontal bar chart of endpoints. `label(row)` / `afterLabel(row)` build
// the tooltip text for the hovered bar; `rows` must be in bar order.
export function endpointBarOptions(rows, { afterLabel, label } = {}) {
  return {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          ...(label ? { label: (context) => label(rows[context.dataIndex]) } : {}),
          ...(afterLabel ? { afterLabel: (context) => afterLabel(rows[context.dataIndex]) } : {}),
        },
      },
    },
    scales: {
      x: { beginAtZero: true, ticks: { precision: 0 } },
      y: {
        grid: { display: false },
        ticks: {
          // chart.js gives a y axis at most half the chart width; the tooltip
          // title still shows the full path.
          callback(value) {
            return truncatePath(this.getLabelForValue(value));
          },
        },
      },
    },
  };
}

export function statusCodePieOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: statusCodeTooltipLabel } },
    },
  };
}
