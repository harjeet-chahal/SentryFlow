import { renderHook, act } from '@testing-library/react';
import usePolling from './usePolling';

// Let pending promise callbacks (fetcher results, state updates) run.
const flush = () =>
  act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });

const advance = (ms) =>
  act(async () => {
    jest.advanceTimersByTime(ms);
  });

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
});

test('loads immediately, then polls on the interval', async () => {
  const fetcher = jest.fn().mockResolvedValueOnce('first').mockResolvedValueOnce('second');
  const { result } = renderHook(() => usePolling(fetcher, { intervalMs: 10000 }));

  expect(result.current.loading).toBe(true);
  expect(result.current.data).toBeNull();

  await flush();
  expect(result.current.loading).toBe(false);
  expect(result.current.data).toBe('first');
  expect(result.current.lastUpdated).toBeInstanceOf(Date);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBeInstanceOf(AbortSignal);

  await advance(9999);
  expect(fetcher).toHaveBeenCalledTimes(1);

  await advance(1);
  await flush();
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(result.current.data).toBe('second');
  expect(result.current.loading).toBe(false);
});

test('a failed background refresh keeps the last good data', async () => {
  const failure = new Error('boom');
  const fetcher = jest.fn().mockResolvedValueOnce('good').mockRejectedValueOnce(failure).mockResolvedValueOnce('recovered');
  const { result } = renderHook(() => usePolling(fetcher, { intervalMs: 10000 }));

  await flush();
  const firstUpdate = result.current.lastUpdated;
  expect(result.current.data).toBe('good');

  await advance(10000);
  await flush();
  expect(result.current.data).toBe('good');
  expect(result.current.error).toBe(failure);
  expect(result.current.loading).toBe(false);
  expect(result.current.lastUpdated).toBe(firstUpdate);

  // Polling carries on after a failure and clears the error on success.
  await advance(10000);
  await flush();
  expect(result.current.data).toBe('recovered');
  expect(result.current.error).toBeNull();
});

test('a first-load failure reports the error and keeps retrying', async () => {
  const failure = new Error('down');
  const fetcher = jest.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce('up');
  const { result } = renderHook(() => usePolling(fetcher, { intervalMs: 10000 }));

  await flush();
  expect(result.current.loading).toBe(false);
  expect(result.current.data).toBeNull();
  expect(result.current.error).toBe(failure);

  await advance(10000);
  await flush();
  expect(result.current.data).toBe('up');
  expect(result.current.error).toBeNull();
});

test('a new query shows the previous result as stale until it loads', async () => {
  const first = jest.fn().mockResolvedValue('A');
  const pending = deferred();
  const second = jest.fn(() => pending.promise);
  const { result, rerender } = renderHook(({ fetcher }) => usePolling(fetcher), {
    initialProps: { fetcher: first },
  });

  await flush();
  expect(result.current.data).toBe('A');
  expect(result.current.isStale).toBe(false);

  rerender({ fetcher: second });
  expect(result.current.data).toBe('A');
  expect(result.current.isStale).toBe(true);
  expect(result.current.loading).toBe(false);

  await act(async () => {
    pending.resolve('B');
  });
  await flush();
  expect(result.current.data).toBe('B');
  expect(result.current.isStale).toBe(false);
});

test('a failed new query does not keep showing the old query’s data', async () => {
  const failure = new Error('nope');
  const first = jest.fn().mockResolvedValue('A');
  const second = jest.fn().mockRejectedValue(failure);
  const { result, rerender } = renderHook(({ fetcher }) => usePolling(fetcher), {
    initialProps: { fetcher: first },
  });

  await flush();
  rerender({ fetcher: second });
  await flush();
  expect(result.current.data).toBeNull();
  expect(result.current.error).toBe(failure);
  expect(result.current.loading).toBe(false);
});

test('changing the query restarts polling for the new query only', async () => {
  const first = jest.fn().mockResolvedValue('A');
  const second = jest.fn().mockResolvedValue('B');
  const { rerender } = renderHook(({ fetcher }) => usePolling(fetcher, { intervalMs: 10000 }), {
    initialProps: { fetcher: first },
  });

  await flush();
  rerender({ fetcher: second });
  await flush();
  await advance(10000);
  await flush();
  expect(first).toHaveBeenCalledTimes(1);
  expect(second).toHaveBeenCalledTimes(2);
});

test('refresh() re-fetches without clearing the data', async () => {
  const pending = deferred();
  const fetcher = jest.fn().mockResolvedValueOnce('A').mockImplementationOnce(() => pending.promise);
  const { result } = renderHook(() => usePolling(fetcher));

  await flush();
  expect(result.current.data).toBe('A');

  act(() => {
    result.current.refresh();
  });
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(result.current.data).toBe('A');
  expect(result.current.refreshing).toBe(true);
  expect(result.current.isStale).toBe(false);

  await act(async () => {
    pending.resolve('A2');
  });
  await flush();
  expect(result.current.data).toBe('A2');
  expect(result.current.refreshing).toBe(false);
});

test('unmounting aborts the request and stops polling', async () => {
  const pending = deferred();
  const fetcher = jest.fn(() => pending.promise);
  const { unmount } = renderHook(() => usePolling(fetcher, { intervalMs: 1000 }));

  const signal = fetcher.mock.calls[0][0];
  expect(signal.aborted).toBe(false);
  unmount();
  expect(signal.aborted).toBe(true);

  await advance(5000);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

test('polling pauses while the tab is hidden', async () => {
  const fetcher = jest.fn().mockResolvedValue('x');
  renderHook(() => usePolling(fetcher, { intervalMs: 1000 }));
  await flush();

  const hidden = jest.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  await advance(3000);
  expect(fetcher).toHaveBeenCalledTimes(1);

  hidden.mockReturnValue(false);
  await advance(1000);
  await flush();
  expect(fetcher).toHaveBeenCalledTimes(2);
  hidden.mockRestore();
});

test('a null fetcher is disabled', () => {
  const { result } = renderHook(() => usePolling(null, { intervalMs: 1000 }));
  expect(result.current).toMatchObject({ data: null, error: null, loading: false, refreshing: false, isStale: false });
});
