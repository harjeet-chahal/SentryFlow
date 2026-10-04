// Small presentational building blocks shared by the dashboard pages.
import React from 'react';
import { format } from 'date-fns';
import { describeApiError } from '../utils/api';

export const PageSpinner = () => (
  <div className="flex items-center justify-center py-24" role="status" aria-label="Loading">
    <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
  </div>
);

export const PageHeader = ({ title, subtitle, children }) => (
  <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
    <div>
      <h1 className="text-2xl font-semibold text-gray-900">{title}</h1>
      {subtitle && (
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-gray-500">{subtitle}</div>
      )}
    </div>
    {children && <div className="flex flex-wrap items-center gap-3">{children}</div>}
  </div>
);

const BADGE_TONES = {
  gray: 'bg-gray-100 text-gray-800',
  blue: 'bg-blue-100 text-blue-800',
  green: 'bg-green-100 text-green-800',
  yellow: 'bg-yellow-100 text-yellow-800',
  orange: 'bg-orange-100 text-orange-800',
  red: 'bg-red-100 text-red-800',
  indigo: 'bg-indigo-100 text-indigo-800',
  pink: 'bg-pink-100 text-pink-800',
};

export const Badge = ({ tone = 'gray', children, title }) => (
  <span
    title={title}
    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${BADGE_TONES[tone] || BADGE_TONES.gray}`}
  >
    {children}
  </span>
);

export const StatCard = ({ title, value, detail, caption }) => (
  <div className="dashboard-card">
    <h3 className="text-lg font-medium text-gray-900">{title}</h3>
    <p className="mt-2 text-3xl font-semibold text-gray-900">{value}</p>
    {detail && <p className="mt-1 text-sm text-gray-700">{detail}</p>}
    {caption && <p className="mt-1 text-sm text-gray-500">{caption}</p>}
  </div>
);

export const ChartCard = ({ title, subtitle, children, className = '' }) => (
  <div className={`chart-container ${className}`}>
    <div className="mb-4">
      <h3 className="text-lg font-medium text-gray-900">{title}</h3>
      {subtitle && <p className="text-sm text-gray-500">{subtitle}</p>}
    </div>
    {children}
  </div>
);

export const EmptyChart = ({ message, heightClass = 'h-72' }) => (
  <div className={`${heightClass} flex items-center justify-center text-center text-sm text-gray-500 px-6`}>
    {message}
  </div>
);

// Full error state for when there is no data to show. 503s (analytics store
// down) get a calmer, explanatory treatment than other failures.
export const ErrorState = ({ error, onRetry, retrying = false, autoRetry = false }) => {
  const info = describeApiError(error);
  if (!info) return null;
  const unavailable = info.kind === 'unavailable';
  return (
    <div className={`rounded-md p-4 ${unavailable ? 'bg-amber-50' : 'bg-red-50'}`} role="alert">
      <h3 className={`text-sm font-medium ${unavailable ? 'text-amber-800' : 'text-red-800'}`}>{info.title}</h3>
      <p className={`mt-1 text-sm ${unavailable ? 'text-amber-700' : 'text-red-700'}`}>{info.message}</p>
      {autoRetry && <p className="mt-1 text-xs text-gray-500">Retrying automatically every 10 seconds.</p>}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="mt-3 text-sm font-medium text-blue-600 hover:text-blue-500 disabled:text-gray-400"
        >
          {retrying ? 'Retrying…' : 'Try again'}
        </button>
      )}
    </div>
  );
};

// "Live · updated 12:00:05", or a small warning when the last refresh failed
// and older data is still on screen.
export const LiveIndicator = ({ lastUpdated, error, refreshing }) => {
  if (!lastUpdated) return null;
  const time = format(lastUpdated, 'HH:mm:ss');
  if (error) {
    const info = describeApiError(error);
    return (
      <span className="inline-flex items-center text-xs text-amber-700" role="status">
        <span className="mr-2 h-2 w-2 rounded-full bg-amber-500" aria-hidden="true" />
        Refresh failed{info ? ` (${info.title.toLowerCase()})` : ''} · showing data from {time}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center text-xs text-gray-500" role="status">
      <span
        className={`mr-2 h-2 w-2 rounded-full bg-green-500 ${refreshing ? 'animate-pulse' : ''}`}
        aria-hidden="true"
      />
      Live · updated {time}
    </span>
  );
};
