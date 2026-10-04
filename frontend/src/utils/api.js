// Small helpers for talking to the SentryFlow API and explaining its errors.

// GET a JSON document. Rejects if the body is not JSON, which is what happens
// when a proxy answers an API path with the SPA's index.html.
export async function getJson(client, url, { params, signal } = {}) {
  const response = await client.get(url, { params, signal });
  const { data } = response;
  if (data === null || typeof data !== 'object') {
    const error = new Error(`Expected JSON from ${url} but received something else.`);
    error.kind = 'bad_response';
    throw error;
  }
  return data;
}

// FastAPI puts a string in `detail`, or a list of validation errors for 422s.
export function formatApiDetail(detail) {
  if (detail === null || detail === undefined || detail === '') return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'string') return item;
        const loc = Array.isArray(item?.loc)
          ? item.loc.filter((part) => !['body', 'query', 'path'].includes(part)).join('.')
          : '';
        const msg = item?.msg ?? JSON.stringify(item);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join('; ');
  }
  if (typeof detail === 'object' && typeof detail.msg === 'string') return detail.msg;
  try {
    return JSON.stringify(detail);
  } catch (err) {
    return String(detail);
  }
}

// Turns an axios error into something presentable: { kind, status, title, message }.
export function describeApiError(error) {
  if (!error) return null;

  if (error.kind === 'bad_response') {
    return {
      kind: 'bad_response',
      status: null,
      title: 'Unexpected response from the API',
      message: `${error.message} Check that the API is reachable at this address.`,
    };
  }

  const status = error.response?.status ?? null;
  const detail = formatApiDetail(error.response?.data?.detail);

  if (status === 503) {
    return {
      kind: 'unavailable',
      status,
      title: 'Analytics are temporarily unavailable',
      message:
        "The analytics store isn't reachable right now. The gateway keeps serving and rate limiting traffic; this view will recover once analytics are back.",
    };
  }
  if (status === 401) {
    return {
      kind: 'unauthorized',
      status,
      title: 'Your session has expired',
      message: 'Sign in again to continue.',
    };
  }
  if (status === 403) {
    return {
      kind: 'forbidden',
      status,
      title: "You don't have access to this data",
      message: detail || 'Ask an administrator if you need access.',
    };
  }
  if (status === 404) {
    return {
      kind: 'not_found',
      status,
      title: 'Not found',
      message: detail || 'The requested resource does not exist.',
    };
  }
  if (status === 400 || status === 422) {
    return {
      kind: 'invalid',
      status,
      title: 'The request was rejected',
      message: detail || 'Some of the values were invalid.',
    };
  }
  if (!error.response) {
    return {
      kind: 'network',
      status: null,
      title: "Can't reach the SentryFlow API",
      message: 'Check your connection and that the API is running.',
    };
  }
  return {
    kind: 'server',
    status,
    title: 'Something went wrong',
    message: detail ? `${detail} (HTTP ${status})` : `The API responded with HTTP ${status}.`,
  };
}

// One-line message for forms: the API's own detail when it sent one.
export function apiErrorMessage(error) {
  const info = describeApiError(error);
  if (!info) return '';
  const detail = formatApiDetail(error.response?.data?.detail);
  if (detail && info.kind !== 'unavailable') return detail;
  return `${info.title}. ${info.message}`;
}
