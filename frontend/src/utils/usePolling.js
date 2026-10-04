import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';

const INITIAL_STATE = {
  data: null,
  dataSource: null,
  error: null,
  errorSource: null,
  lastUpdated: null,
};

const isAbort = (error) =>
  axios.isCancel(error) || error?.name === 'AbortError' || error?.name === 'CanceledError';

/**
 * Runs `fetcher(signal)` now, again whenever `fetcher` changes, and every
 * `intervalMs` if that is > 0. Pass a memoised fetcher (useCallback); pass
 * null to disable.
 *
 * - `loading` is true only while there is nothing to show yet (first load).
 * - Background refreshes keep the last good data; a failed refresh sets
 *   `error` alongside it.
 * - When the query changes, the previous result stays visible with
 *   `isStale: true` until the new one arrives (or fails).
 * - Polling pauses while the tab is hidden and stops on unmount/query change.
 */
export default function usePolling(fetcher, { intervalMs = 0 } = {}) {
  const [state, setState] = useState(INITIAL_STATE);
  const [inFlight, setInFlight] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!fetcher) return undefined;

    let cancelled = false;
    let timer = null;
    let controller = null;

    function schedule() {
      if (!cancelled && intervalMs > 0) timer = setTimeout(tick, intervalMs);
    }

    function tick() {
      if (typeof document !== 'undefined' && document.hidden) schedule();
      else run();
    }

    async function run() {
      controller = new AbortController();
      setInFlight(true);
      try {
        const data = await fetcher(controller.signal);
        if (cancelled) return;
        setState({ data, dataSource: fetcher, error: null, errorSource: null, lastUpdated: new Date() });
      } catch (error) {
        if (cancelled || isAbort(error)) return;
        setState((prev) => {
          // Keep the last good data only if it answers this same query.
          const sameQuery = prev.dataSource === fetcher;
          return {
            data: sameQuery ? prev.data : null,
            dataSource: sameQuery ? prev.dataSource : null,
            lastUpdated: sameQuery ? prev.lastUpdated : null,
            error,
            errorSource: fetcher,
          };
        });
      } finally {
        if (!cancelled) {
          setInFlight(false);
          schedule();
        }
      }
    }

    run();

    return () => {
      cancelled = true;
      clearTimeout(timer);
      if (controller) controller.abort();
    };
  }, [fetcher, intervalMs, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  if (!fetcher) {
    return { data: null, error: null, loading: false, refreshing: false, isStale: false, lastUpdated: null, refresh };
  }

  const error = state.errorSource === fetcher ? state.error : null;
  return {
    data: state.data,
    error,
    loading: state.data === null && error === null,
    refreshing: inFlight,
    isStale: state.data !== null && state.dataSource !== fetcher,
    lastUpdated: state.lastUpdated,
    refresh,
  };
}
