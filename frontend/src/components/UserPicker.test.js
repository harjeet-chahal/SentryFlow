import React, { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAuth } from './auth/AuthContext';
import UserPicker, { PICKER_LIMIT } from './UserPicker';

jest.mock('./auth/AuthContext', () => ({ useAuth: jest.fn() }));

const accounts = Array.from({ length: 25 }, (_, i) => ({
  id: `u${i}`,
  username: `user${String(i).padStart(2, '0')}`,
  email: `user${i}@example.com`,
}));
accounts.push({ id: 'bob', username: 'bob', email: 'bob@acme.example.com' });

let authAxios;

// Answers like GET /auth/users: searched, in username order, limited.
const serveDirectory = (url, { params }) => {
  const term = (params.search ?? '').toLowerCase();
  const matches = accounts
    .filter((u) => !term || u.username.includes(term) || u.email.includes(term))
    .sort((a, b) => a.username.localeCompare(b.username));
  return Promise.resolve({ data: { total: matches.length, users: matches.slice(0, params.limit) } });
};

const Harness = () => {
  const [value, setValue] = useState('');
  return (
    <>
      <label htmlFor="picker">User</label>
      <UserPicker id="picker" value={value} onChange={setValue} emptyLabel="All users" />
      <output>{`chosen: ${value || 'nobody'}`}</output>
    </>
  );
};

const searchCalls = () => authAxios.get.mock.calls.map(([, config]) => config.params);

beforeEach(() => {
  authAxios = { get: jest.fn(serveDirectory) };
  useAuth.mockReturnValue({ authAxios });
});

test('asks the server for one page of accounts, not all of them', async () => {
  render(<Harness />);

  expect(await screen.findByRole('option', { name: 'bob (bob@acme.example.com)' })).toBeInTheDocument();
  expect(searchCalls()).toEqual([{ limit: PICKER_LIMIT }]);
  // The first option is the empty choice.
  expect(screen.getAllByRole('option')).toHaveLength(PICKER_LIMIT + 1);
  expect(screen.getByText('Showing 20 of 26 users. Search to narrow the list.')).toBeInTheDocument();
});

test('searching is done by the server, once typing pauses', async () => {
  render(<Harness />);
  await screen.findByRole('option', { name: 'bob (bob@acme.example.com)' });

  userEvent.type(screen.getByLabelText('Search users'), 'acme');

  await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(2));
  expect(searchCalls()).toEqual([{ limit: PICKER_LIMIT }, { search: 'acme', limit: PICKER_LIMIT }]);
  expect(screen.queryByText(/Search to narrow/)).not.toBeInTheDocument();
});

test('the chosen account stays listed after the search moves on', async () => {
  render(<Harness />);
  await screen.findByRole('option', { name: 'bob (bob@acme.example.com)' });

  userEvent.selectOptions(screen.getByLabelText('User'), 'bob');
  expect(screen.getByText('chosen: bob')).toBeInTheDocument();

  userEvent.type(screen.getByLabelText('Search users'), 'user2');
  // user24 is past the first page, so it only appears once the search is served.
  expect(await screen.findByRole('option', { name: 'user24 (user24@example.com)' })).toBeInTheDocument();
  expect(searchCalls()).toContainEqual({ search: 'user2', limit: PICKER_LIMIT });
  expect(screen.getByRole('option', { name: 'bob (bob@acme.example.com)' })).toBeInTheDocument();
  expect(screen.getByLabelText('User')).toHaveValue('bob');
});

test('falls back to a user ID field when the directory cannot be loaded', async () => {
  authAxios.get.mockImplementation(() => Promise.reject({ response: { status: 503, data: {} } }));
  render(<Harness />);

  expect(await screen.findByText("Couldn't load the user list; enter the user's ID instead.")).toBeInTheDocument();
  userEvent.type(screen.getByLabelText('User'), 'u7');
  expect(screen.getByText('chosen: u7')).toBeInTheDocument();
});
