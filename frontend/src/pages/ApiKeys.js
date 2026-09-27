import React, { useCallback, useMemo, useState } from 'react';
import { useAuth, publicApiUrl } from '../components/auth/AuthContext';
import CopyButton from '../components/CopyButton';
import { PageHeader, PageSpinner, ErrorState, Badge } from '../components/ui';
import { formatDateTime, formatRelative, maskKey, parseApiDate } from '../utils/analytics';
import { getJson, apiErrorMessage } from '../utils/api';
import usePolling from '../utils/usePolling';

const th = 'px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider';
const td = 'px-4 py-4 whitespace-nowrap text-sm text-gray-500';
// Keeps the table within the card on narrower screens.
const xlOnly = 'hidden xl:table-cell';

const createdTime = (key) => parseApiDate(key.created_at)?.getTime() ?? 0;

// Active keys first, newest first within each group.
const sortKeys = (keys) =>
  [...keys].sort((a, b) => {
    if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
    return createdTime(b) - createdTime(a);
  });

const NewKeyBanner = ({ apiKey, onDismiss }) => (
  <div className="mb-4 rounded-md bg-green-50 p-4" role="status">
    <h3 className="text-sm font-medium text-green-800">API key “{apiKey.name}” created</h3>
    <p className="mt-1 text-sm text-green-700">
      Copy it now and store it somewhere safe: anyone with this key can call the API as you.
    </p>
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <code className="break-all rounded bg-white px-3 py-2 font-mono text-sm text-gray-900 border border-green-200">
        {apiKey.key}
      </code>
      <CopyButton text={apiKey.key} label="Copy key" />
    </div>
    <p className="mt-3 text-sm text-green-700">Try it:</p>
    <pre className="mt-1 overflow-x-auto rounded-md bg-gray-900 p-3 text-xs text-gray-100">
      <code>{`curl -H "x-api-key: ${apiKey.key}" ${publicApiUrl('/api/v1/hello')}`}</code>
    </pre>
    <button
      type="button"
      className="mt-3 text-sm font-medium text-green-800 hover:text-green-700"
      onClick={onDismiss}
    >
      Dismiss
    </button>
  </div>
);

const ApiKeys = () => {
  const { authAxios } = useAuth();
  const [newKeyName, setNewKeyName] = useState('');
  const [creating, setCreating] = useState(false);
  const [createKeyError, setCreateKeyError] = useState(null);
  const [createdKey, setCreatedKey] = useState(null);
  const [revealed, setRevealed] = useState({});
  const [revokingId, setRevokingId] = useState(null);
  const [actionError, setActionError] = useState(null);

  const fetchKeys = useCallback((signal) => getJson(authAxios, '/auth/apikeys', { signal }), [authAxios]);
  const { data, error, loading, refreshing, refresh } = usePolling(fetchKeys);
  const apiKeys = useMemo(() => sortKeys(Array.isArray(data) ? data : []), [data]);

  // Create new API key
  const handleCreateKey = async (e) => {
    e.preventDefault();

    const name = newKeyName.trim();
    if (!name) {
      setCreateKeyError('API key name is required');
      return;
    }

    setCreating(true);
    setCreateKeyError(null);
    try {
      const response = await authAxios.post('/auth/apikeys/create', { name });
      setCreatedKey(response.data);
      setNewKeyName('');
      refresh();
    } catch (err) {
      console.error('Error creating API key:', err);
      setCreateKeyError(apiErrorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  // Revoke an API key (the row stays, marked as revoked)
  const handleRevoke = async (apiKey) => {
    const confirmed = window.confirm(
      `Revoke “${apiKey.name}”? Requests using this key will be rejected immediately. This can't be undone.`
    );
    if (!confirmed) return;

    setRevokingId(apiKey.id);
    setActionError(null);
    try {
      await authAxios.delete(`/auth/apikeys/${apiKey.id}`);
      if (createdKey?.id === apiKey.id) setCreatedKey(null);
      refresh();
    } catch (err) {
      console.error('Error revoking API key:', err);
      setActionError(apiErrorMessage(err));
    } finally {
      setRevokingId(null);
    }
  };

  const toggleReveal = (id) => setRevealed((prev) => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="space-y-6">
      <PageHeader
        title="API Keys"
        subtitle={<span>Send a key in the x-api-key header to call the API through the gateway.</span>}
      />

      {/* Create new API key form */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Create New API Key</h2>

        {createKeyError && (
          <div className="mb-4 rounded-md bg-red-50 p-4" role="alert">
            <h3 className="text-sm font-medium text-red-800">{createKeyError}</h3>
          </div>
        )}

        {createdKey && <NewKeyBanner apiKey={createdKey} onDismiss={() => setCreatedKey(null)} />}

        <form onSubmit={handleCreateKey} className="space-y-4">
          <div>
            <label htmlFor="key-name" className="block text-sm font-medium text-gray-700">
              Key Name
            </label>
            <input
              type="text"
              id="key-name"
              className="form-input mt-1 sm:text-sm"
              placeholder="e.g., Production API Key"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
            />
          </div>

          <div>
            <button
              type="submit"
              disabled={creating}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
            >
              {creating ? 'Creating…' : 'Create API Key'}
            </button>
          </div>
        </form>
      </div>

      {/* API keys list */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-4 py-5 sm:px-6">
          <h2 className="text-lg font-medium text-gray-900">Your API Keys</h2>
          <p className="mt-1 text-sm text-gray-500">
            Revoked keys stay listed for reference but no longer authenticate requests.
          </p>
        </div>

        {actionError && (
          <div className="mx-4 mb-4 rounded-md bg-red-50 p-4" role="alert">
            <h3 className="text-sm font-medium text-red-800">{actionError}</h3>
          </div>
        )}

        <div className="border-t border-gray-200">
          {loading && <PageSpinner />}

          {!data && error && (
            <div className="p-4">
              <ErrorState error={error} onRetry={refresh} retrying={refreshing} />
            </div>
          )}

          {data && error && (
            <p className="px-6 py-3 text-sm text-amber-800 bg-amber-50" role="status">
              Couldn't refresh the list ({apiErrorMessage(error)}); it may be out of date.
            </p>
          )}

          {data && apiKeys.length === 0 && (
            <p className="px-6 py-5 text-sm text-gray-500">
              No API keys yet. Create your first one using the form above.
            </p>
          )}

          {apiKeys.length > 0 && (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th scope="col" className={th}>Name</th>
                    <th scope="col" className={th}>Key</th>
                    <th scope="col" className={`${th} ${xlOnly}`}>Created</th>
                    <th scope="col" className={th}>Last used</th>
                    <th scope="col" className={th}>Status</th>
                    <th scope="col" className={th}>
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {apiKeys.map((apiKey) => (
                    <tr key={apiKey.id} className={apiKey.is_active ? '' : 'bg-gray-50'}>
                      <td className={`${td} font-medium ${apiKey.is_active ? 'text-gray-900' : 'text-gray-500'}`}>
                        {apiKey.name}
                      </td>
                      {/* No nowrap here, so a revealed key wraps instead of widening the table. */}
                      <td className="px-4 py-4 text-sm text-gray-500">
                        <div className="flex items-center gap-3">
                          <code
                            className={`min-w-0 font-mono break-all ${apiKey.is_active ? 'text-gray-900' : 'text-gray-400 line-through'}`}
                          >
                            {revealed[apiKey.id] ? apiKey.key : maskKey(apiKey.key)}
                          </code>
                          <button
                            type="button"
                            onClick={() => toggleReveal(apiKey.id)}
                            className="text-sm font-medium text-blue-600 hover:text-blue-500"
                          >
                            {revealed[apiKey.id] ? 'Hide' : 'Reveal'}
                          </button>
                          <CopyButton text={apiKey.key} />
                        </div>
                      </td>
                      <td className={`${td} ${xlOnly}`}>{formatDateTime(apiKey.created_at, 'MMM d, yyyy')}</td>
                      <td className={td} title={apiKey.last_used_at ? formatDateTime(apiKey.last_used_at) : undefined}>
                        {apiKey.last_used_at ? formatRelative(parseApiDate(apiKey.last_used_at)) : 'Never'}
                      </td>
                      <td className={td}>
                        {apiKey.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Revoked</Badge>}
                      </td>
                      <td className={`${td} text-right`}>
                        {apiKey.is_active && (
                          <button
                            type="button"
                            onClick={() => handleRevoke(apiKey)}
                            disabled={revokingId === apiKey.id}
                            className="text-sm font-medium text-red-600 hover:text-red-500 disabled:text-gray-400"
                          >
                            {revokingId === apiKey.id ? 'Revoking…' : 'Revoke'}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ApiKeys;
