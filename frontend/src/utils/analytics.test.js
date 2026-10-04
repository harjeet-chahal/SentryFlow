import {
  TIME_RANGES,
  EMPTY_VALUE,
  formatBucketLabel,
  formatNumber,
  formatLatency,
  formatPercent,
  formatShare,
  parseApiDate,
  epochToDate,
  formatRelative,
  maskKey,
  truncatePath,
  stepSecondsOf,
  bucketLabels,
  hasLatencyData,
  isolatedPointRadius,
  buildRequestsChartData,
  buildLatencyChartData,
  statusCodeBreakdown,
  buildStatusCodeChartData,
  statusCodeTooltipLabel,
  buildTopEndpointsChartData,
  topEndpointTooltipLines,
  buildAllowedVsRateLimitedChartData,
  throttledEndpointRows,
  buildRateLimitedByEndpointChartData,
  throttledEndpointTooltipLabel,
  throttledUserRows,
  countLineOptions,
  latencyLineOptions,
  endpointBarOptions,
  statusCodePieOptions,
} from './analytics';

// Epoch seconds for a wall-clock time in the machine's local zone.
const localEpoch = (...args) => new Date(...args).getTime() / 1000;

const T0 = Date.UTC(2026, 8, 24, 10) / 1000;

const usageFixture = {
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
    { t: T0 + 7200, requests: 4, errors: 1, rate_limited: 4, avg_ms: null, p95_ms: null },
    { t: T0 + 10800, requests: 20, errors: 2, rate_limited: 0, avg_ms: 4, p95_ms: 9 },
  ],
  status_codes: { '2xx': 1100, '3xx': 0, '4xx': 120, '5xx': 14 },
  top_endpoints: [
    { endpoint: '/api/v1/hello', requests: 1000, errors: 3, rate_limited: 20, p95_ms: 8 },
    { endpoint: '/api/v1/other', requests: 234, errors: 9, rate_limited: 10, p95_ms: null },
  ],
};

const rateLimitsFixture = {
  range: '1h',
  step_seconds: 60,
  scope: { user_id: null, username: null },
  totals: { requests: 60, rate_limited: 12, rate_limited_rate: 20 },
  series: [
    { t: T0, allowed: 9, rate_limited: 1 },
    { t: T0 + 60, allowed: 39, rate_limited: 11 },
  ],
  by_endpoint: [
    { endpoint: '/a', requests: 10, rate_limited: 0 },
    { endpoint: '/b', requests: 20, rate_limited: 2 },
    { endpoint: '/c', requests: 30, rate_limited: 10 },
  ],
  by_user: [
    { user_id: 'u1', username: 'alice', requests: 50, rate_limited: 2 },
    { user_id: 'u2', username: 'bob', requests: 5, rate_limited: 0 },
    { user_id: 'u3', username: 'carol', requests: 5, rate_limited: 10 },
  ],
};

describe('time ranges', () => {
  test('match the API bucket sizes', () => {
    expect(TIME_RANGES.map((r) => [r.value, r.stepSeconds])).toEqual([
      ['1h', 60],
      ['24h', 3600],
      ['7d', 21600],
      ['30d', 86400],
    ]);
  });
});

describe('formatBucketLabel', () => {
  test('minute buckets (1h) show local HH:mm', () => {
    expect(formatBucketLabel(localEpoch(2026, 8, 24, 13, 5), 60)).toBe('13:05');
  });

  test('hour buckets (24h) show local HH:mm', () => {
    expect(formatBucketLabel(localEpoch(2026, 8, 24, 7, 0), 3600)).toBe('07:00');
  });

  test('6-hour buckets (7d) show the local date and time', () => {
    expect(formatBucketLabel(localEpoch(2026, 8, 24, 18, 0), 21600)).toBe('Sep 24 18:00');
  });

  test('day buckets (30d) show the UTC date, whatever the local zone', () => {
    expect(formatBucketLabel(Date.UTC(2026, 8, 24, 0, 0) / 1000, 86400)).toBe('Sep 24');
    expect(formatBucketLabel(Date.UTC(2026, 8, 24, 23, 59) / 1000, 86400)).toBe('Sep 24');
    expect(formatBucketLabel(Date.UTC(2026, 11, 31) / 1000, 86400)).toBe('Dec 31');
  });

  test('missing timestamps give an empty label', () => {
    expect(formatBucketLabel(null, 60)).toBe('');
    expect(formatBucketLabel(undefined, 86400)).toBe('');
  });
});

describe('number formatters', () => {
  test('formatNumber', () => {
    expect(formatNumber(12)).toBe('12');
    expect(formatNumber(0)).toBe('0');
    expect(formatNumber(1234567)).toBe((1234567).toLocaleString());
    expect(formatNumber(null)).toBe(EMPTY_VALUE);
    expect(formatNumber(undefined)).toBe(EMPTY_VALUE);
  });

  test('formatLatency renders null as a dash', () => {
    expect(formatLatency(null)).toBe('—');
    expect(formatLatency(undefined)).toBe('—');
    expect(formatLatency(Number.NaN)).toBe('—');
  });

  test('formatLatency rounds sensibly', () => {
    expect(formatLatency(0)).toBe('0 ms');
    expect(formatLatency(8)).toBe('8 ms');
    expect(formatLatency(3.24)).toBe('3.2 ms');
    expect(formatLatency(250.6)).toBe('251 ms');
    expect(formatLatency(1234.4)).toBe(`${(1234).toLocaleString()} ms`);
  });

  test('formatPercent takes a 0-100 value', () => {
    expect(formatPercent(0.97)).toBe('0.97%');
    expect(formatPercent(2.43)).toBe('2.43%');
    expect(formatPercent(12.345)).toBe('12.3%');
    expect(formatPercent(100)).toBe('100%');
    expect(formatPercent(0)).toBe('0%');
    expect(formatPercent(0.004)).toBe('<0.01%');
    expect(formatPercent(null)).toBe('—');
  });

  test('formatShare', () => {
    expect(formatShare(20, 1000)).toBe('2%');
    expect(formatShare(1, 3)).toBe('33.3%');
    expect(formatShare(5, 0)).toBe('—');
  });
});

describe('dates', () => {
  test('naive ISO timestamps from the API are treated as UTC', () => {
    expect(parseApiDate('2026-09-24T12:00:00').toISOString()).toBe('2026-09-24T12:00:00.000Z');
    expect(parseApiDate('2026-09-24T12:00:00.123456').toISOString()).toBe('2026-09-24T12:00:00.123Z');
  });

  test('timestamps with a zone are kept as they are', () => {
    expect(parseApiDate('2026-09-24T12:00:00Z').toISOString()).toBe('2026-09-24T12:00:00.000Z');
    expect(parseApiDate('2026-09-24T14:00:00+02:00').toISOString()).toBe('2026-09-24T12:00:00.000Z');
  });

  test('bad input gives null', () => {
    expect(parseApiDate(null)).toBeNull();
    expect(parseApiDate('')).toBeNull();
    expect(parseApiDate('not a date')).toBeNull();
  });

  test('epochToDate and formatRelative', () => {
    expect(epochToDate(null)).toBeNull();
    const seen = epochToDate(1727128800);
    expect(seen.toISOString()).toBe('2024-09-23T22:00:00.000Z');
    const now = new Date(seen.getTime() + 5 * 60 * 1000);
    expect(formatRelative(seen, now)).toBe('5 minutes ago');
    expect(formatRelative(seen, new Date(seen.getTime() + 10 * 1000))).toBe('just now');
    expect(formatRelative(null)).toBe('—');
  });
});

describe('string helpers', () => {
  test('maskKey shows the first 8 characters', () => {
    expect(maskKey('0123456789abcdef')).toBe('01234567…');
    expect(maskKey('short')).toBe('short');
    expect(maskKey(null)).toBe('');
  });

  test('truncatePath keeps the end of long paths, at a segment boundary', () => {
    expect(truncatePath('/api/v1/hello')).toBe('/api/v1/hello');
    expect(truncatePath('/api/v1/inventory/items/export')).toBe('…/items/export');
    expect(truncatePath('/api/v1/customers/search')).toBe('…/v1/customers/search');
    expect(truncatePath('/api/v1/averyveryverylongsegmentname')).toBe('…ryverylongsegmentname');
    expect(truncatePath('/api/v1/averyveryverylongsegmentname').length).toBeLessThanOrEqual(22);
  });
});

describe('series helpers', () => {
  test('stepSecondsOf prefers step_seconds, then the range', () => {
    expect(stepSecondsOf({ step_seconds: 21600 })).toBe(21600);
    expect(stepSecondsOf({ range: '30d' })).toBe(86400);
    expect(stepSecondsOf({ series: [{ t: 0 }, { t: 60 }] })).toBe(60);
  });

  test('bucketLabels uses the response step', () => {
    const day = { step_seconds: 86400, series: [{ t: Date.UTC(2026, 8, 23) / 1000 }, { t: Date.UTC(2026, 8, 24) / 1000 }] };
    expect(bucketLabels(day)).toEqual(['Sep 23', 'Sep 24']);
  });

  test('hasLatencyData', () => {
    expect(hasLatencyData(usageFixture)).toBe(true);
    expect(hasLatencyData({ series: [{ t: 1, avg_ms: null, p95_ms: null }] })).toBe(false);
    expect(hasLatencyData(undefined)).toBe(false);
  });

  test('isolatedPointRadius only shows values with gaps on both sides', () => {
    const dataset = { data: [null, 5, null, 6, 7, null] };
    const radius = (dataIndex) => isolatedPointRadius({ dataset, dataIndex });
    expect(radius(0)).toBe(0);
    expect(radius(1)).toBeGreaterThan(0);
    expect(radius(3)).toBe(0);
    expect(radius(4)).toBe(0);
    expect(isolatedPointRadius({ dataset: { data: [4] }, dataIndex: 0 })).toBeGreaterThan(0);
    expect(isolatedPointRadius({})).toBe(0);
  });
});

describe('usage charts', () => {
  test('requests chart has requests and rate-limited datasets', () => {
    const data = buildRequestsChartData(usageFixture);
    expect(data.labels).toHaveLength(4);
    expect(data.datasets.map((d) => d.label)).toEqual(['Requests', 'Rate limited (429)']);
    expect(data.datasets[0].data).toEqual([10, 0, 4, 20]);
    expect(data.datasets[1].data).toEqual([1, 0, 4, 0]);
  });

  test('latency chart keeps null buckets as gaps', () => {
    const data = buildLatencyChartData(usageFixture);
    expect(data.labels).toHaveLength(4);
    const [p95, avg] = data.datasets;
    expect(p95.label).toBe('p95');
    expect(p95.data).toEqual([7, null, null, 9]);
    expect(avg.label).toBe('Average');
    expect(avg.data).toEqual([3.1, null, null, 4]);
    expect(p95.spanGaps).toBe(false);
    expect(avg.spanGaps).toBe(false);
  });

  test('latency chart turns missing values into null', () => {
    const data = buildLatencyChartData({ step_seconds: 60, series: [{ t: T0, requests: 0 }] });
    expect(data.datasets[0].data).toEqual([null]);
    expect(data.datasets[1].data).toEqual([null]);
  });

  test('empty responses give empty charts rather than throwing', () => {
    for (const build of [buildRequestsChartData, buildLatencyChartData, buildAllowedVsRateLimitedChartData]) {
      const data = build(undefined);
      expect(data.labels).toEqual([]);
      data.datasets.forEach((dataset) => expect(dataset.data).toEqual([]));
    }
    expect(buildTopEndpointsChartData({}).labels).toEqual([]);
    expect(buildRateLimitedByEndpointChartData(null).labels).toEqual([]);
    expect(buildStatusCodeChartData(undefined).datasets[0].data).toEqual([0, 0, 0, 0]);
  });

  test('status code chart always has the four classes in order', () => {
    const data = buildStatusCodeChartData({ '5xx': 2, '2xx': 8 });
    expect(data.labels).toEqual(['2xx', '3xx', '4xx', '5xx']);
    expect(data.datasets[0].data).toEqual([8, 0, 0, 2]);
    expect(data.datasets[0].backgroundColor).toHaveLength(4);
  });

  test('status code breakdown has counts and shares', () => {
    const { total, rows } = statusCodeBreakdown(usageFixture.status_codes);
    expect(total).toBe(1234);
    expect(rows.map((r) => r.count)).toEqual([1100, 0, 120, 14]);
    expect(rows[0].share).toBeCloseTo(89.14, 2);
    expect(statusCodeBreakdown({}).rows.every((r) => r.share === 0)).toBe(true);
  });

  test('status code tooltip shows the count and percent', () => {
    const context = { label: '4xx', raw: 120, dataset: { data: [1100, 0, 120, 14] } };
    expect(statusCodeTooltipLabel(context)).toBe('4xx: 120 (9.72%)');
    expect(statusCodePieOptions().plugins.tooltip.callbacks.label(context)).toBe('4xx: 120 (9.72%)');
  });

  test('top endpoints chart is a single requests series', () => {
    const data = buildTopEndpointsChartData(usageFixture);
    expect(data.labels).toEqual(['/api/v1/hello', '/api/v1/other']);
    expect(data.datasets).toHaveLength(1);
    expect(data.datasets[0].data).toEqual([1000, 234]);
    expect(buildTopEndpointsChartData(usageFixture, 1).labels).toEqual(['/api/v1/hello']);
  });

  test('top endpoint tooltip lines', () => {
    expect(topEndpointTooltipLines(usageFixture.top_endpoints[1])).toEqual([
      'Errors: 9',
      'Rate limited: 10',
      'p95: —',
    ]);
    expect(topEndpointTooltipLines(undefined)).toEqual([]);
  });
});

describe('rate limit charts', () => {
  test('allowed vs rate limited', () => {
    const data = buildAllowedVsRateLimitedChartData(rateLimitsFixture);
    expect(data.labels).toHaveLength(2);
    expect(data.datasets.map((d) => d.label)).toEqual(['Allowed', 'Rate limited (429)']);
    expect(data.datasets[0].data).toEqual([9, 39]);
    expect(data.datasets[1].data).toEqual([1, 11]);
  });

  test('throttled endpoints are filtered and sorted', () => {
    expect(throttledEndpointRows(rateLimitsFixture).map((r) => r.endpoint)).toEqual(['/c', '/b']);
    const data = buildRateLimitedByEndpointChartData(rateLimitsFixture);
    expect(data.labels).toEqual(['/c', '/b']);
    expect(data.datasets[0].data).toEqual([10, 2]);
  });

  test('throttled endpoint tooltip', () => {
    expect(throttledEndpointTooltipLabel({ endpoint: '/c', requests: 30, rate_limited: 10 })).toBe(
      '10 of 30 requests (33.3%)'
    );
  });

  test('most throttled users', () => {
    expect(throttledUserRows(rateLimitsFixture).map((r) => r.username)).toEqual(['carol', 'alice']);
    expect(throttledUserRows({ by_user: [] })).toEqual([]);
    expect(throttledUserRows(undefined)).toEqual([]);
  });
});

describe('chart options', () => {
  test('line tooltips format values and show gaps as a dash', () => {
    const latency = latencyLineOptions();
    expect(latency.plugins.tooltip.callbacks.label({ dataset: { label: 'p95' }, raw: null })).toBe('p95: —');
    expect(latency.plugins.tooltip.callbacks.label({ dataset: { label: 'p95' }, raw: 8 })).toBe('p95: 8 ms');
    const counts = countLineOptions('Requests');
    expect(counts.scales.y.title.text).toBe('Requests');
    expect(counts.plugins.tooltip.callbacks.label({ dataset: { label: 'Requests' }, raw: 1234 })).toBe(
      `Requests: ${(1234).toLocaleString()}`
    );
  });

  test('endpoint bar tooltips look up the hovered row', () => {
    const rows = usageFixture.top_endpoints;
    const options = endpointBarOptions(rows, { afterLabel: topEndpointTooltipLines });
    expect(options.indexAxis).toBe('y');
    expect(options.plugins.tooltip.callbacks.afterLabel({ dataIndex: 0 })).toEqual([
      'Errors: 3',
      'Rate limited: 20',
      'p95: 8 ms',
    ]);
    expect(options.plugins.tooltip.callbacks.label).toBeUndefined();
  });
});
