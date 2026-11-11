import { useEffect, useState } from 'react'
import {
  Check, FileCode, LoaderCircle, Play, RefreshCw, ShieldCheck, Terminal,
} from 'lucide-react'
import { getApimaticStatus, invokeApimaticTool } from './api'
import type { APIMaticStatus } from './types'

export default function APIMaticPage({ toast }: { toast?: (t: { message: string; kind: 'success' | 'error' | 'info' }) => void }) {
  const [manifest, setManifest] = useState<APIMaticStatus | null>(null)
  const [loadingManifest, setLoadingManifest] = useState(true)

  const [selectedTool, setSelectedTool] = useState('paypal_get_order_details')
  const [orderId, setOrderId] = useState('sample-order-maya-sony')
  const [captureId, setCaptureId] = useState('sample-capture-maya')
  const [refundAmount, setRefundAmount] = useState('50.00')
  const [refundCurrency, setRefundCurrency] = useState('USD')
  const [noteToPayer, setNoteToPayer] = useState('DropBack 14-day price protection difference refund')

  const [executing, setExecuting] = useState(false)
  const [response, setResponse] = useState<any | null>(null)
  const [latency, setLatency] = useState<number | null>(null)
  const [error, setError] = useState('')

  const fetchStatus = async () => {
    setLoadingManifest(true)
    try {
      const data = await getApimaticStatus()
      setManifest(data)
    } catch {
      toast?.({ kind: 'error', message: 'Could not fetch APIMatic context plugin status.' })
    } finally {
      setLoadingManifest(false)
    }
  }

  useEffect(() => {
    void fetchStatus().then(() => {
      // Auto-ping sandbox health on page load to show live connectivity
      void invokeApimaticTool('paypal_check_sandbox_health', {}).then(r => {
        setResponse(r)
        setSelectedTool('paypal_check_sandbox_health')
      }).catch(() => undefined)
    })
  }, [])

  const handleRunTool = async () => {
    setExecuting(true)
    setError('')
    setResponse(null)
    setLatency(null)

    let args: Record<string, any> = {}
    if (selectedTool === 'paypal_get_order_details') {
      args = { order_id: orderId }
    } else if (selectedTool === 'paypal_get_capture_status') {
      args = { capture_id: captureId }
    } else if (selectedTool === 'paypal_issue_capture_refund') {
      args = {
        capture_id: captureId,
        amount: Number(refundAmount),
        currency: refundCurrency,
        note_to_payer: noteToPayer,
      }
    }

    const t0 = performance.now()
    try {
      const result = await invokeApimaticTool(selectedTool, args)
      const t1 = performance.now()
      setLatency(Math.round(t1 - t0))
      setResponse(result)
      toast?.({ kind: 'success', message: `MCP tool ${selectedTool} executed successfully.` })
    } catch (err: any) {
      const t1 = performance.now()
      setLatency(Math.round(t1 - t0))
      setError(err?.message || 'Execution error.')
      toast?.({ kind: 'error', message: err?.message || 'MCP tool execution failed.' })
    } finally {
      setExecuting(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }} data-testid="apimatic-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">APIMATIC CONTEXT PLUGINS · PAYPAL SANDBOX MCP</div>
          <h1>APIMatic MCP Protocol Sandbox</h1>
          <p>
            Grounding autonomous agents with verified OpenAPI schemas for PayPal Orders v2 and Payments v2.
            APIMatic context plugins prevent LLM hallucinations by injecting authoritative endpoint contracts into model prompts.
          </p>
        </div>
        <div className="heading-actions">
          <button type="button" className="button button-light" onClick={fetchStatus} disabled={loadingManifest}>
            <RefreshCw size={15} /> Refresh Manifest
          </button>
        </div>
      </div>

      <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: 8, background: '#7e22ce', color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 800 }}>
            <Terminal size={20} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <b style={{ fontSize: 14, color: '#1e293b' }}>{manifest?.plugin_name || 'PayPal Developer Sandbox Context Plugin'}</b>
              <span className="mcp-pill">v{manifest?.version || '2026.04.1'}</span>
              <span style={{ fontSize: 11, color: '#16a34a', background: '#ecfdf5', padding: '2px 8px', borderRadius: 10, fontWeight: 700 }}>
                ● Active
              </span>
            </div>
            <span style={{ fontSize: 12, color: '#64748b' }}>
              Spec: OpenAPI 3.0.3 · Target: PayPal Sandbox Orders v2 & Payments v2 · Tools: {manifest?.tools_count ?? 4}
            </span>
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <span style={{ fontSize: 11, color: '#64748b', display: 'block' }}>APIMATIC SPONSOR CATEGORY</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: '#7e22ce' }}>PayPal AI Hackathon 2026</span>
        </div>
      </div>

      <div className="apimatic-panel">
        {/* LEFT COLUMN: MANIFEST & SCHEMAS */}
        <div className="apimatic-card">
          <div className="apimatic-card-head">
            <h3>APIMatic Context Plugin Manifest</h3>
            <span style={{ fontSize: 11, color: '#64748b', display: 'flex', alignItems: 'center', gap: 4 }}>
              <ShieldCheck size={14} color="#16a34a" /> Zero Hallucinations
            </span>
          </div>

          <p style={{ margin: 0, fontSize: 12, color: '#475569', lineHeight: 1.6 }}>
            Modern AI agents frequently hallucinate deprecated PayPal v1 endpoints (e.g. <code>/v1/payments/payment</code>).
            DropBack integrates APIMatic Context Plugins into the agent's MCP runtime, enforcing strict type definitions
            and endpoint paths directly derived from official PayPal OpenAPI 3.0 specs.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
            <b style={{ fontSize: 12, color: '#1e293b' }}>Authoritative Schemas Injected:</b>
            <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
                <FileCode size={14} color="#3b82f6" />
                <b>Orders v2:</b> <code>POST /v2/checkout/orders</code>, <code>GET /v2/checkout/orders/&#123;id&#125;</code>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
                <FileCode size={14} color="#10b981" />
                <b>Payments v2:</b> <code>POST /v2/payments/captures/&#123;id&#125;/refund</code>, <code>GET /v2/payments/captures/&#123;id&#125;</code>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
            <b style={{ fontSize: 12, color: '#1e293b' }}>Registered MCP Sandbox Tools:</b>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {(manifest?.tools || [
                { name: 'paypal_check_sandbox_health', description: 'Validate PayPal sandbox API connectivity and credentials.' },
                { name: 'paypal_get_order_details', description: 'Retrieve verified order details, items, amounts, and capture links.' },
                { name: 'paypal_get_capture_status', description: 'Inspect capture ID status and refundable balance.' },
                { name: 'paypal_issue_capture_refund', description: 'Execute capture refund via Payments v2 with idempotency.' },
              ]).map(tool => (
                <div
                  key={tool.name}
                  style={{
                    background: selectedTool === tool.name ? '#f5f3ff' : '#ffffff',
                    border: `1px solid ${selectedTool === tool.name ? '#c084fc' : '#e2e8f0'}`,
                    borderRadius: 6,
                    padding: '8px 12px',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  onClick={() => setSelectedTool(tool.name)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <code style={{ fontSize: 12, fontWeight: 700, color: selectedTool === tool.name ? '#7e22ce' : '#1e293b' }}>
                      {tool.name}
                    </code>
                    {selectedTool === tool.name && <Check size={14} color="#7e22ce" />}
                  </div>
                  <p style={{ margin: '3px 0 0', fontSize: 11, color: '#64748b' }}>{tool.description}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: INTERACTIVE MCP RUNNER */}
        <div className="apimatic-card">
          <div className="apimatic-card-head">
            <h3>Interactive MCP Tool Runner</h3>
            <span className="mcp-pill">LIVE SANDBOX</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>
              Select MCP Tool:
              <select
                className="mcp-tool-select"
                style={{ width: '100%', marginTop: 4 }}
                value={selectedTool}
                onChange={e => setSelectedTool(e.target.value)}
              >
                <option value="paypal_get_order_details">paypal_get_order_details</option>
                <option value="paypal_get_capture_status">paypal_get_capture_status</option>
                <option value="paypal_issue_capture_refund">paypal_issue_capture_refund</option>
                <option value="paypal_check_sandbox_health">paypal_check_sandbox_health</option>
              </select>
            </label>

            {/* DYNAMIC ARGUMENTS */}
            {selectedTool === 'paypal_get_order_details' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>
                  Order ID:
                  <input
                    type="text"
                    style={{ width: '100%', height: 38, border: '1px solid #cbd5e1', borderRadius: 6, padding: '0 10px', fontSize: 12, marginTop: 4 }}
                    value={orderId}
                    onChange={e => setOrderId(e.target.value)}
                    placeholder="e.g. sample-order-maya-sony or PayPal Order ID"
                  />
                </label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button type="button" className="button button-light small-button" onClick={() => setOrderId('sample-order-maya-sony')} style={{ fontSize: 10 }}>
                    Maya Chen Order
                  </button>
                  <button type="button" className="button button-light small-button" onClick={() => setOrderId('sample-order-rohan-breville')} style={{ fontSize: 10 }}>
                    Rohan Shah Order
                  </button>
                </div>
              </div>
            )}

            {selectedTool === 'paypal_get_capture_status' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>
                  Capture ID:
                  <input
                    type="text"
                    style={{ width: '100%', height: 38, border: '1px solid #cbd5e1', borderRadius: 6, padding: '0 10px', fontSize: 12, marginTop: 4 }}
                    value={captureId}
                    onChange={e => setCaptureId(e.target.value)}
                    placeholder="e.g. sample-capture-maya"
                  />
                </label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button type="button" className="button button-light small-button" onClick={() => setCaptureId('sample-capture-maya')} style={{ fontSize: 10 }}>
                    Sample Capture Maya
                  </button>
                  <button type="button" className="button button-light small-button" onClick={() => setCaptureId('sample-capture-rohan')} style={{ fontSize: 10 }}>
                    Sample Capture Rohan
                  </button>
                </div>
              </div>
            )}

            {selectedTool === 'paypal_issue_capture_refund' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>
                  Capture ID:
                  <input
                    type="text"
                    style={{ width: '100%', height: 38, border: '1px solid #cbd5e1', borderRadius: 6, padding: '0 10px', fontSize: 12, marginTop: 4 }}
                    value={captureId}
                    onChange={e => setCaptureId(e.target.value)}
                  />
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <label style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>
                    Refund Amount:
                    <input
                      type="number"
                      step="0.01"
                      style={{ width: '100%', height: 38, border: '1px solid #cbd5e1', borderRadius: 6, padding: '0 10px', fontSize: 12, marginTop: 4 }}
                      value={refundAmount}
                      onChange={e => setRefundAmount(e.target.value)}
                    />
                  </label>
                  <label style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>
                    Currency:
                    <input
                      type="text"
                      style={{ width: '100%', height: 38, border: '1px solid #cbd5e1', borderRadius: 6, padding: '0 10px', fontSize: 12, marginTop: 4 }}
                      value={refundCurrency}
                      onChange={e => setRefundCurrency(e.target.value)}
                    />
                  </label>
                </div>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>
                  Note to Payer:
                  <input
                    type="text"
                    style={{ width: '100%', height: 38, border: '1px solid #cbd5e1', borderRadius: 6, padding: '0 10px', fontSize: 12, marginTop: 4 }}
                    value={noteToPayer}
                    onChange={e => setNoteToPayer(e.target.value)}
                  />
                </label>
              </div>
            )}

            {selectedTool === 'paypal_check_sandbox_health' && (
              <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 6, padding: 12, fontSize: 11, color: '#64748b' }}>
                Verifies OAuth2 client credentials against <code>https://api-m.sandbox.paypal.com/v1/oauth2/token</code> and tests Orders v2 readiness.
              </div>
            )}

            <button
              type="button"
              className="button button-dark"
              data-testid="mcp-execute-btn"
              onClick={handleRunTool}
              disabled={executing}
              style={{ marginTop: 8 }}
            >
              {executing ? <><LoaderCircle size={15} className="spin" /> Executing via APIMatic Context…</> : <><Play size={15} /> Execute MCP Tool</>}
            </button>
          </div>

          {/* RESPONSE VIEWER */}
          <div style={{ marginTop: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#334155' }}>Tool Response:</span>
              {latency !== null && (
                <span style={{ fontSize: 11, color: error ? '#dc2626' : '#16a34a', fontWeight: 700 }}>
                  {error ? 'Execution Failed' : '200 OK'} · Latency: {latency}ms
                </span>
              )}
            </div>

            {error && (
              <div style={{ background: '#fef2f2', border: '1px solid #fecaca', color: '#dc2626', padding: 10, borderRadius: 6, fontSize: 11 }}>
                {error}
              </div>
            )}

            {response && (
              <pre className="json-viewer" data-testid="mcp-response">
                {JSON.stringify(response, null, 2)}
              </pre>
            )}

            {!response && !error && (
              <div style={{ border: '1px dashed #cbd5e1', borderRadius: 6, padding: 20, textAlign: 'center', color: '#94a3b8', fontSize: 11 }}>
                Click "Execute MCP Tool" to run the validated PayPal OpenAPI operation.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
