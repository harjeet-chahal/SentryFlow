import React from 'react';
import { publicApiUrl } from './auth/AuthContext';

// Shell commands that call the gateway with an API key. The key is traded for
// a short-lived token at /auth/token, and the gateway accepts only the token.
const GatewayCurlExample = ({ apiKey, className = '' }) => (
  <pre className={`overflow-x-auto rounded-md bg-gray-900 p-3 text-xs text-gray-100 ${className}`}>
    <code>
      {[
        `TOKEN=$(curl -s -X POST -H "x-api-key: ${apiKey}" ${publicApiUrl('/auth/token')} \\`,
        `  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')`,
        `curl -H "Authorization: Bearer $TOKEN" ${publicApiUrl('/api/v1/hello')}`,
      ].join('\n')}
    </code>
  </pre>
);

export default GatewayCurlExample;
