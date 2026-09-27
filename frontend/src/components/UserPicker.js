import React, { useCallback, useState } from 'react';
import { useAuth } from './auth/AuthContext';
import { getJson } from '../utils/api';
import { formatNumber } from '../utils/analytics';
import usePolling from '../utils/usePolling';
import useDebouncedValue from '../utils/useDebouncedValue';

// Matches shown at a time. The server does the searching, so the picker never
// loads every account to show a few.
export const PICKER_LIMIT = 20;

const userLabel = (user) => (user.email ? `${user.username} (${user.email})` : user.username);

// Admin control for choosing one account: a search box over GET /auth/users
// and a select of the matches. Label the select by passing its `id`. If the
// directory cannot be loaded it falls back to a plain user-ID field.
const UserPicker = ({ id, value, onChange, emptyLabel, className = '' }) => {
  const { authAxios } = useAuth();
  const [search, setSearch] = useState('');
  const query = useDebouncedValue(search.trim(), 300);
  // The chosen account stays listed after the search moves past it.
  const [chosen, setChosen] = useState(null);

  const fetchMatches = useCallback(
    (signal) =>
      getJson(authAxios, '/auth/users', {
        params: query ? { search: query, limit: PICKER_LIMIT } : { limit: PICKER_LIMIT },
        signal,
      }),
    [authAxios, query]
  );
  const { data, error, loading } = usePolling(fetchMatches);

  if (error && !data) {
    return (
      <>
        <input
          id={id}
          className={className}
          placeholder="User ID"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <p className="mt-1 text-xs text-amber-700">Couldn't load the user list; enter the user's ID instead.</p>
      </>
    );
  }

  const matches = data?.users ?? [];
  const keepChosen = chosen && chosen.id === value && !matches.some((u) => u.id === chosen.id);
  const options = keepChosen ? [chosen, ...matches] : matches;

  const handleSelect = (event) => {
    setChosen(options.find((u) => u.id === event.target.value) ?? null);
    onChange(event.target.value);
  };

  return (
    <div className="space-y-2">
      <input
        type="search"
        aria-label="Search users"
        placeholder="Search by username or email"
        className={className}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <select id={id} className={className} value={value} onChange={handleSelect} disabled={loading}>
        <option value="">{loading ? 'Loading users…' : emptyLabel}</option>
        {options.map((user) => (
          <option key={user.id} value={user.id}>
            {userLabel(user)}
          </option>
        ))}
      </select>
      {data && data.total > matches.length && (
        <p className="text-xs text-gray-500">
          Showing {matches.length} of {formatNumber(data.total)} {query ? 'matches' : 'users'}. Search to narrow the
          list.
        </p>
      )}
    </div>
  );
};

export default UserPicker;
