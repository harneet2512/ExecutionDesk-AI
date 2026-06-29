'use client';

import { useState } from 'react';
import CodeSnippet from '@/components/CodeSnippet';

type EndpointGroup = 'api-keys' | 'webhooks' | 'runs' | 'orders' | 'portfolio' | 'market';

interface Endpoint {
  method: 'GET' | 'POST' | 'DELETE' | 'PUT' | 'PATCH';
  path: string;
  description: string;
  snippets: {
    python: string;
    javascript: string;
    curl: string;
  };
}

const METHOD_COLORS: Record<string, string> = {
  GET: 'gain',
  POST: 'text-[var(--color-probability)]',
  DELETE: 'loss',
  PUT: 'text-[var(--chart-3)]',
  PATCH: 'text-[var(--chart-4)]',
};

const ENDPOINT_GROUPS: Record<EndpointGroup, { label: string; endpoints: Endpoint[] }> = {
  'api-keys': {
    label: 'API Keys',
    endpoints: [
      {
        method: 'POST',
        path: '/api/v1/api-keys',
        description: 'Generate a new API key. The full key is returned only once -- store it securely.',
        snippets: {
          python: `import requests

resp = requests.post(
    "http://localhost:8000/api/v1/api-keys",
    headers={"Authorization": "Bearer YOUR_JWT"},
    json={
        "name": "My Trading Bot",
        "permissions": ["read", "trade"]
    }
)
data = resp.json()
print(f"Key ID: {data['key_id']}")
print(f"API Key: {data['api_key']}")  # Store this!`,
          javascript: `const resp = await fetch('/api/v1/api-keys', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer YOUR_JWT',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    name: 'My Trading Bot',
    permissions: ['read', 'trade'],
  }),
});
const data = await resp.json();
console.log('Key ID:', data.key_id);
console.log('API Key:', data.api_key); // Store this!`,
          curl: `curl -X POST http://localhost:8000/api/v1/api-keys \\
  -H "Authorization: Bearer YOUR_JWT" \\
  -H "Content-Type: application/json" \\
  -d '{"name": "My Trading Bot", "permissions": ["read", "trade"]}'`,
        },
      },
      {
        method: 'GET',
        path: '/api/v1/api-keys',
        description: 'List all API keys. Returns key prefix only, never the full key.',
        snippets: {
          python: `resp = requests.get(
    "http://localhost:8000/api/v1/api-keys",
    headers={"Authorization": "Bearer YOUR_JWT"}
)
for key in resp.json():
    print(f"{key['name']}: {key['key_prefix']}...")`,
          javascript: `const resp = await fetch('/api/v1/api-keys', {
  headers: { 'Authorization': 'Bearer YOUR_JWT' },
});
const keys = await resp.json();
keys.forEach(k => console.log(\`\${k.name}: \${k.key_prefix}...\`));`,
          curl: `curl http://localhost:8000/api/v1/api-keys \\
  -H "Authorization: Bearer YOUR_JWT"`,
        },
      },
      {
        method: 'DELETE',
        path: '/api/v1/api-keys/{key_id}',
        description: 'Revoke an API key immediately. The key can no longer be used for authentication.',
        snippets: {
          python: `resp = requests.delete(
    f"http://localhost:8000/api/v1/api-keys/{key_id}",
    headers={"Authorization": "Bearer YOUR_JWT"}
)
print(resp.json())  # {"key_id": "...", "revoked": true}`,
          javascript: `const resp = await fetch(\`/api/v1/api-keys/\${keyId}\`, {
  method: 'DELETE',
  headers: { 'Authorization': 'Bearer YOUR_JWT' },
});
console.log(await resp.json());`,
          curl: `curl -X DELETE http://localhost:8000/api/v1/api-keys/KEY_ID \\
  -H "Authorization: Bearer YOUR_JWT"`,
        },
      },
      {
        method: 'POST',
        path: '/api/v1/api-keys/{key_id}/rotate',
        description: 'Rotate an API key. The old key remains valid for 24 hours (grace period).',
        snippets: {
          python: `resp = requests.post(
    f"http://localhost:8000/api/v1/api-keys/{key_id}/rotate",
    headers={"Authorization": "Bearer YOUR_JWT"}
)
data = resp.json()
print(f"New Key: {data['api_key']}")
print(f"Old key valid until: {data['previous_key_expires_at']}")`,
          javascript: `const resp = await fetch(\`/api/v1/api-keys/\${keyId}/rotate\`, {
  method: 'POST',
  headers: { 'Authorization': 'Bearer YOUR_JWT' },
});
const data = await resp.json();
console.log('New Key:', data.api_key);`,
          curl: `curl -X POST http://localhost:8000/api/v1/api-keys/KEY_ID/rotate \\
  -H "Authorization: Bearer YOUR_JWT"`,
        },
      },
    ],
  },
  webhooks: {
    label: 'Webhooks',
    endpoints: [
      {
        method: 'POST',
        path: '/api/v1/webhooks',
        description: 'Register a webhook endpoint. You will receive a signing secret for HMAC verification.',
        snippets: {
          python: `resp = requests.post(
    "http://localhost:8000/api/v1/webhooks",
    headers={"Authorization": "Bearer YOUR_JWT"},
    json={
        "url": "https://your-server.com/webhook",
        "events": ["trade.filled", "run.completed"]
    }
)
data = resp.json()
print(f"Webhook ID: {data['webhook_id']}")
print(f"Secret: {data['secret']}")  # Store for HMAC verification`,
          javascript: `const resp = await fetch('/api/v1/webhooks', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer YOUR_JWT',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    url: 'https://your-server.com/webhook',
    events: ['trade.filled', 'run.completed'],
  }),
});
const data = await resp.json();
console.log('Secret:', data.secret); // Store for HMAC verification`,
          curl: `curl -X POST http://localhost:8000/api/v1/webhooks \\
  -H "Authorization: Bearer YOUR_JWT" \\
  -H "Content-Type: application/json" \\
  -d '{"url": "https://your-server.com/webhook", "events": ["trade.filled", "run.completed"]}'`,
        },
      },
      {
        method: 'GET',
        path: '/api/v1/webhooks',
        description: 'List all active webhooks for your tenant.',
        snippets: {
          python: `resp = requests.get(
    "http://localhost:8000/api/v1/webhooks",
    headers={"Authorization": "Bearer YOUR_JWT"}
)
for hook in resp.json():
    print(f"{hook['url']}: {hook['events']}")`,
          javascript: `const resp = await fetch('/api/v1/webhooks', {
  headers: { 'Authorization': 'Bearer YOUR_JWT' },
});
const hooks = await resp.json();
hooks.forEach(h => console.log(h.url, h.events));`,
          curl: `curl http://localhost:8000/api/v1/webhooks \\
  -H "Authorization: Bearer YOUR_JWT"`,
        },
      },
      {
        method: 'DELETE',
        path: '/api/v1/webhooks/{webhook_id}',
        description: 'Remove a webhook. No further events will be delivered.',
        snippets: {
          python: `resp = requests.delete(
    f"http://localhost:8000/api/v1/webhooks/{webhook_id}",
    headers={"Authorization": "Bearer YOUR_JWT"}
)
print(resp.json())`,
          javascript: `const resp = await fetch(\`/api/v1/webhooks/\${webhookId}\`, {
  method: 'DELETE',
  headers: { 'Authorization': 'Bearer YOUR_JWT' },
});
console.log(await resp.json());`,
          curl: `curl -X DELETE http://localhost:8000/api/v1/webhooks/WEBHOOK_ID \\
  -H "Authorization: Bearer YOUR_JWT"`,
        },
      },
      {
        method: 'POST',
        path: '/api/v1/webhooks/{webhook_id}/test',
        description: 'Send a test ping event to verify your webhook endpoint.',
        snippets: {
          python: `resp = requests.post(
    f"http://localhost:8000/api/v1/webhooks/{webhook_id}/test",
    headers={"Authorization": "Bearer YOUR_JWT"}
)
print(resp.json())  # {"status": "test_queued"}`,
          javascript: `const resp = await fetch(\`/api/v1/webhooks/\${webhookId}/test\`, {
  method: 'POST',
  headers: { 'Authorization': 'Bearer YOUR_JWT' },
});
console.log(await resp.json());`,
          curl: `curl -X POST http://localhost:8000/api/v1/webhooks/WEBHOOK_ID/test \\
  -H "Authorization: Bearer YOUR_JWT"`,
        },
      },
    ],
  },
  runs: {
    label: 'Runs',
    endpoints: [
      {
        method: 'GET',
        path: '/api/v1/runs',
        description: 'List all trading runs. Supports pagination via limit/offset query parameters.',
        snippets: {
          python: `resp = requests.get(
    "http://localhost:8000/api/v1/runs",
    headers={"X-API-Key": "edai_test_..."},
    params={"limit": 10, "offset": 0}
)
for run in resp.json():
    print(f"{run['run_id']}: {run['status']}")`,
          javascript: `const resp = await fetch('/api/v1/runs?limit=10', {
  headers: { 'X-API-Key': 'edai_test_...' },
});
const runs = await resp.json();`,
          curl: `curl "http://localhost:8000/api/v1/runs?limit=10" \\
  -H "X-API-Key: edai_test_..."`,
        },
      },
      {
        method: 'GET',
        path: '/api/v1/runs/{run_id}',
        description: 'Get detailed information about a specific run including nodes, orders, and evals.',
        snippets: {
          python: `resp = requests.get(
    f"http://localhost:8000/api/v1/runs/{run_id}",
    headers={"X-API-Key": "edai_test_..."}
)
detail = resp.json()
print(f"Status: {detail['run']['status']}")
print(f"Nodes: {len(detail['nodes'])}")`,
          javascript: `const resp = await fetch(\`/api/v1/runs/\${runId}\`, {
  headers: { 'X-API-Key': 'edai_test_...' },
});
const detail = await resp.json();`,
          curl: `curl http://localhost:8000/api/v1/runs/RUN_ID \\
  -H "X-API-Key: edai_test_..."`,
        },
      },
    ],
  },
  orders: {
    label: 'Orders',
    endpoints: [
      {
        method: 'GET',
        path: '/api/v1/orders',
        description: 'List all orders across runs.',
        snippets: {
          python: `resp = requests.get(
    "http://localhost:8000/api/v1/orders",
    headers={"X-API-Key": "edai_test_..."}
)
for order in resp.json():
    print(f"{order['order_id']}: {order['status']}")`,
          javascript: `const resp = await fetch('/api/v1/orders', {
  headers: { 'X-API-Key': 'edai_test_...' },
});
const orders = await resp.json();`,
          curl: `curl http://localhost:8000/api/v1/orders \\
  -H "X-API-Key: edai_test_..."`,
        },
      },
    ],
  },
  portfolio: {
    label: 'Portfolio',
    endpoints: [
      {
        method: 'GET',
        path: '/api/v1/portfolio/snapshots',
        description: 'Get portfolio snapshots over time for performance tracking.',
        snippets: {
          python: `resp = requests.get(
    "http://localhost:8000/api/v1/portfolio/snapshots",
    headers={"X-API-Key": "edai_test_..."}
)
for snap in resp.json():
    print(f"{snap['ts']}: {snap['total_value_usd']}")`,
          javascript: `const resp = await fetch('/api/v1/portfolio/snapshots', {
  headers: { 'X-API-Key': 'edai_test_...' },
});
const snapshots = await resp.json();`,
          curl: `curl http://localhost:8000/api/v1/portfolio/snapshots \\
  -H "X-API-Key: edai_test_..."`,
        },
      },
    ],
  },
  market: {
    label: 'Market Data',
    endpoints: [
      {
        method: 'GET',
        path: '/api/v1/market/prices',
        description: 'Get current market prices for supported assets.',
        snippets: {
          python: `resp = requests.get(
    "http://localhost:8000/api/v1/market/prices",
    headers={"X-API-Key": "edai_test_..."},
    params={"symbols": "BTC-USD,ETH-USD"}
)
prices = resp.json()`,
          javascript: `const resp = await fetch('/api/v1/market/prices?symbols=BTC-USD,ETH-USD', {
  headers: { 'X-API-Key': 'edai_test_...' },
});
const prices = await resp.json();`,
          curl: `curl "http://localhost:8000/api/v1/market/prices?symbols=BTC-USD,ETH-USD" \\
  -H "X-API-Key: edai_test_..."`,
        },
      },
    ],
  },
};

const EVENT_TYPES = [
  { event: 'trade.filled', description: 'A trade order has been filled (partially or fully).' },
  { event: 'trade.failed', description: 'A trade order has failed to execute.' },
  { event: 'run.completed', description: 'A trading run has completed successfully.' },
  { event: 'run.failed', description: 'A trading run has failed.' },
  { event: 'approval.needed', description: 'A trade requires human approval before execution.' },
  { event: 'policy.blocked', description: 'A trade was blocked by policy engine rules.' },
];

const HMAC_SNIPPET = {
  python: `import hmac
import hashlib

def verify_webhook(payload: bytes, signature: str, secret: str) -> bool:
    """Verify webhook HMAC-SHA256 signature."""
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

# In your webhook handler:
# signature = request.headers["X-Webhook-Signature"]
# is_valid = verify_webhook(request.body, signature, YOUR_SECRET)`,
  javascript: `const crypto = require('crypto');

function verifyWebhook(payload, signature, secret) {
  const expected = 'sha256=' + crypto
    .createHmac('sha256', secret)
    .update(payload)
    .digest('hex');
  return crypto.timingSafeEqual(
    Buffer.from(expected),
    Buffer.from(signature)
  );
}

// In your webhook handler:
// const sig = req.headers['x-webhook-signature'];
// const valid = verifyWebhook(req.rawBody, sig, YOUR_SECRET);`,
  curl: `# Compute expected signature
echo -n '{"event":"trade.filled","data":{}}' | \\
  openssl dgst -sha256 -hmac "YOUR_SECRET" -hex`,
};

export default function DocsPage() {
  const [activeGroup, setActiveGroup] = useState<EndpointGroup>('api-keys');
  const [expandedEndpoint, setExpandedEndpoint] = useState<string | null>(null);

  const groups = Object.entries(ENDPOINT_GROUPS) as [EndpointGroup, typeof ENDPOINT_GROUPS[EndpointGroup]][];
  const currentGroup = ENDPOINT_GROUPS[activeGroup];

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <h1 className="text-xl font-semibold mb-2 theme-text">API Documentation</h1>
      <p className="theme-text-secondary mb-8">
        Reference for the ExecutiveDesk AI REST API. All endpoints require authentication via JWT bearer token or API key.
      </p>

      {/* Authentication Section */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold mb-4 theme-text">Authentication</h2>
        <div className="theme-surface rounded-lg border theme-border p-6 space-y-4">
          <div>
            <h3 className="font-medium theme-text mb-2">JWT Bearer Token</h3>
            <p className="text-sm theme-text-secondary">
              Obtain a JWT via <code className="px-1 py-0.5 rounded theme-elevated text-sm">POST /api/v1/auth/login</code> and
              pass it as <code className="px-1 py-0.5 rounded theme-elevated text-sm">Authorization: Bearer TOKEN</code>.
            </p>
          </div>
          <div>
            <h3 className="font-medium theme-text mb-2">API Key</h3>
            <p className="text-sm theme-text-secondary">
              Generate an API key below, then pass it as <code className="px-1 py-0.5 rounded theme-elevated text-sm">X-API-Key: edai_test_...</code>.
              Keys are scoped by permission: <code className="px-1 py-0.5 rounded theme-elevated text-sm">read</code>,{' '}
              <code className="px-1 py-0.5 rounded theme-elevated text-sm">trade</code>,{' '}
              <code className="px-1 py-0.5 rounded theme-elevated text-sm">admin</code>.
            </p>
          </div>
          <div>
            <h3 className="font-medium theme-text mb-2">Rate Limits</h3>
            <p className="text-sm theme-text-secondary">
              Write endpoints: 10 req/min. Read endpoints: 30 req/min. Status polling: 120 req/min.
              Exceeded limits return <code className="px-1 py-0.5 rounded theme-elevated text-sm">429</code> with a{' '}
              <code className="px-1 py-0.5 rounded theme-elevated text-sm">Retry-After</code> header.
            </p>
          </div>
        </div>
      </section>

      {/* Endpoint Groups Navigation */}
      <div className="flex gap-2 mb-6 flex-wrap">
        {groups.map(([id, group]) => (
          <button
            key={id}
            onClick={() => {
              setActiveGroup(id);
              setExpandedEndpoint(null);
            }}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeGroup === id
                ? 'theme-elevated theme-text border theme-border-strong shadow-sm'
                : 'theme-text-secondary hover:theme-text hover:bg-[var(--color-fill-ghost-hover)]'
            }`}
          >
            {group.label}
          </button>
        ))}
      </div>

      {/* Endpoints List */}
      <section className="space-y-4 mb-10">
        <h2 className="text-xl font-semibold theme-text">{currentGroup.label}</h2>
        {currentGroup.endpoints.map((ep) => {
          const key = `${ep.method}-${ep.path}`;
          const isExpanded = expandedEndpoint === key;
          return (
            <div key={key} className="border theme-border rounded-lg overflow-hidden">
              <button
                onClick={() => setExpandedEndpoint(isExpanded ? null : key)}
                className="w-full flex items-center gap-3 px-4 py-3 theme-surface hover:bg-[var(--color-fill-ghost-hover)] transition-colors text-left"
              >
                <span className={`font-mono text-sm font-bold w-16 ${METHOD_COLORS[ep.method]}`}>
                  {ep.method}
                </span>
                <span className="font-mono text-sm theme-text flex-1">{ep.path}</span>
                <span className="text-xs theme-text-secondary hidden sm:inline">{ep.description.slice(0, 60)}...</span>
                <svg
                  className={`w-4 h-4 theme-text-secondary transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {isExpanded && (
                <div className="p-4 border-t theme-border space-y-4">
                  <p className="text-sm theme-text-secondary">{ep.description}</p>
                  <CodeSnippet snippets={ep.snippets} />
                </div>
              )}
            </div>
          );
        })}
      </section>

      {/* Webhook Events Reference */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold mb-4 theme-text">Webhook Events</h2>
        <div className="theme-surface rounded-lg border theme-border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b theme-border">
                <th className="px-4 py-3 text-left font-medium theme-text">Event</th>
                <th className="px-4 py-3 text-left font-medium theme-text">Description</th>
              </tr>
            </thead>
            <tbody>
              {EVENT_TYPES.map((evt) => (
                <tr key={evt.event} className="border-b theme-border last:border-b-0">
                  <td className="px-4 py-3 font-mono text-sm theme-text">{evt.event}</td>
                  <td className="px-4 py-3 theme-text-secondary">{evt.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* HMAC Verification */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold mb-4 theme-text">Webhook Signature Verification</h2>
        <p className="text-sm theme-text-secondary mb-4">
          Every webhook delivery includes an <code className="px-1 py-0.5 rounded theme-elevated text-sm">X-Webhook-Signature</code>{' '}
          header with an HMAC-SHA256 signature. Always verify this signature before processing the payload.
        </p>
        <CodeSnippet snippets={HMAC_SNIPPET} title="Verify Webhook Signature" />
      </section>

      {/* Error Responses */}
      <section>
        <h2 className="text-xl font-semibold mb-4 theme-text">Error Responses</h2>
        <div className="theme-surface rounded-lg border theme-border p-6">
          <p className="text-sm theme-text-secondary mb-4">
            All errors follow a consistent JSON envelope:
          </p>
          <pre className="p-4 rounded-lg theme-elevated text-sm font-mono theme-text overflow-x-auto">
{`{
  "error": {
    "code": "HTTP_404",
    "message": "Resource not found",
    "request_id": "abc-123-def",
    "remediation": "Check the resource ID"
  }
}`}
          </pre>
          <div className="mt-4 space-y-2">
            <div className="flex gap-2 text-sm">
              <code className="px-2 py-0.5 rounded theme-elevated font-mono">400</code>
              <span className="theme-text-secondary">Invalid request body or parameters</span>
            </div>
            <div className="flex gap-2 text-sm">
              <code className="px-2 py-0.5 rounded theme-elevated font-mono">401</code>
              <span className="theme-text-secondary">Missing or invalid authentication</span>
            </div>
            <div className="flex gap-2 text-sm">
              <code className="px-2 py-0.5 rounded theme-elevated font-mono">403</code>
              <span className="theme-text-secondary">Insufficient permissions</span>
            </div>
            <div className="flex gap-2 text-sm">
              <code className="px-2 py-0.5 rounded theme-elevated font-mono">404</code>
              <span className="theme-text-secondary">Resource not found</span>
            </div>
            <div className="flex gap-2 text-sm">
              <code className="px-2 py-0.5 rounded theme-elevated font-mono">429</code>
              <span className="theme-text-secondary">Rate limit exceeded (check Retry-After header)</span>
            </div>
            <div className="flex gap-2 text-sm">
              <code className="px-2 py-0.5 rounded theme-elevated font-mono">500</code>
              <span className="theme-text-secondary">Internal server error</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
