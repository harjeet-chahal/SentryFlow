import React, { useMemo, useState } from 'react';
import { useAuth } from './auth/AuthContext';
import { ALGORITHMS, MAX_LIMIT_VALUE, validateRuleInput } from '../utils/limits';
import { apiErrorMessage } from '../utils/api';

const inputClass = 'form-input mt-1 sm:text-sm disabled:bg-gray-100 disabled:text-gray-500';

// Admin form that creates or updates a rule with PUT /limits. A rule is keyed
// by (user, endpoint), so both are locked while editing an existing rule.
// Remount it (change `key`) to reset it.
const RateLimitRuleForm = ({ rule, defaults, users, usersLoading, usersError, onSaved, onCancel }) => {
  const { authAxios } = useAuth();
  const editing = Boolean(rule);
  const [form, setForm] = useState(() => ({
    user_id: rule?.user_id ?? '',
    endpoint: rule?.endpoint ?? '*',
    requests_per_minute: String(rule?.requests_per_minute ?? defaults?.requests_per_minute ?? 60),
    burst_capacity: String(rule?.burst_capacity ?? defaults?.burst_capacity ?? 10),
    algorithm: rule?.algorithm ?? defaults?.algorithm ?? 'sliding_window',
  }));
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);

  const userOptions = useMemo(
    () => [...(users ?? [])].sort((a, b) => String(a.username).localeCompare(String(b.username))),
    [users]
  );

  const update = (field) => (event) => setForm((prev) => ({ ...prev, [field]: event.target.value }));

  const handleSubmit = async (event) => {
    event.preventDefault();
    const { payload, error } = validateRuleInput(form);
    if (error) {
      setFormError(error);
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const response = await authAxios.put('/limits', payload);
      onSaved(response.data && typeof response.data === 'object' ? response.data : payload);
    } catch (err) {
      setFormError(apiErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  let userField;
  if (editing) {
    userField = <input id="rule-user" className={inputClass} value={rule.username ?? rule.user_id} disabled />;
  } else if (usersError) {
    // The user list comes from the analytics store; fall back to a raw ID.
    userField = (
      <>
        <input
          id="rule-user"
          className={inputClass}
          placeholder="User ID"
          value={form.user_id}
          onChange={update('user_id')}
        />
        <p className="mt-1 text-xs text-amber-700">Couldn't load the user list; enter the user's ID instead.</p>
      </>
    );
  } else {
    userField = (
      <select
        id="rule-user"
        className={inputClass}
        value={form.user_id}
        onChange={update('user_id')}
        disabled={usersLoading}
      >
        <option value="">{usersLoading ? 'Loading users…' : 'Select a user'}</option>
        {userOptions.map((u) => (
          <option key={u.id} value={u.id}>
            {u.username}
            {u.email ? ` (${u.email})` : ''}
          </option>
        ))}
      </select>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      {formError && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-800" role="alert">
          {formError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-6">
        <div className="md:col-span-3">
          <label htmlFor="rule-user" className="block text-sm font-medium text-gray-700">
            User
          </label>
          {userField}
        </div>
        <div className="md:col-span-3">
          <label htmlFor="rule-endpoint" className="block text-sm font-medium text-gray-700">
            Endpoint
          </label>
          <input
            id="rule-endpoint"
            className={`${inputClass} font-mono`}
            placeholder="* or /api/v1/hello"
            value={form.endpoint}
            onChange={update('endpoint')}
            disabled={editing}
          />
          <p className="mt-1 text-xs text-gray-500">
            <code>*</code> covers every endpoint for this user; an exact path overrides it for that path.
          </p>
        </div>
        <div className="md:col-span-2">
          <label htmlFor="rule-rpm" className="block text-sm font-medium text-gray-700">
            Requests / minute
          </label>
          <input
            id="rule-rpm"
            type="number"
            min="1"
            max={MAX_LIMIT_VALUE}
            step="1"
            className={inputClass}
            value={form.requests_per_minute}
            onChange={update('requests_per_minute')}
          />
        </div>
        <div className="md:col-span-2">
          <label htmlFor="rule-burst" className="block text-sm font-medium text-gray-700">
            Burst capacity
          </label>
          <input
            id="rule-burst"
            type="number"
            min="1"
            max={MAX_LIMIT_VALUE}
            step="1"
            className={inputClass}
            value={form.burst_capacity}
            onChange={update('burst_capacity')}
          />
          <p className="mt-1 text-xs text-gray-500">Used by the token bucket algorithm.</p>
        </div>
        <div className="md:col-span-2">
          <label htmlFor="rule-algorithm" className="block text-sm font-medium text-gray-700">
            Algorithm
          </label>
          <select id="rule-algorithm" className={inputClass} value={form.algorithm} onChange={update('algorithm')}>
            {ALGORITHMS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
        >
          {submitting ? 'Saving…' : editing ? 'Update rule' : 'Save rule'}
        </button>
        {editing && (
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium rounded-md bg-gray-200 text-gray-800 hover:bg-gray-300"
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
};

export default RateLimitRuleForm;
