import { useEffect, useState } from 'react'
import { AlertCircle, Check, Code2, ExternalLink, LoaderCircle, Play, RefreshCw, ShieldCheck } from 'lucide-react'
import { api, getApimaticStatus, invokeApimaticTool } from './api'
import type { APIMaticStatus } from './types'

type SandboxOrder = {
  order_id: string
  capture_id: string | null
  buyer_name: string
  item_name: string
  amount: number
  currency: string
  status: string
}

const TOOLS = [
  { name: 'paypal_check_sandbox_health', label: 'Check sandbox health', kind: 'health', description: 'Verify OAuth and PayPal sandbox connectivity.' },
  { name: 'paypal_get_order_details', label: 'Get order details', kind: 'order', description: 'Read a PayPal Orders v2 record.' },
  { name: 'paypal_get_capture_status', label: 'Get capture status', kind: 'capture', description: 'Read a captured payment and its status.' },
  { name: 'paypal_issue_capture_refund', label: 'Issue capture refund', kind: 'refund', description: 'Send a partial or full refund to a captured payment.' },
]

export default function APIMaticPage({ toast }: { toast?: (t: { message: string; kind: 'success' | 'error' | 'info' }) => void }) {
  const [manifest, setManifest] = useState<APIMaticStatus | null>(null)
  const [sandboxOrders, setSandboxOrders] = useState<SandboxOrder[]>([])
  const [selectedTool, setSelectedTool] = useState('paypal_check_sandbox_health')
  const [orderId, setOrderId] = useState('')
  const [captureId, setCaptureId] = useState('')
  const [refundAmount, setRefundAmount] = useState('')
  const [refundCurrency, setRefundCurrency] = useState('USD')
  const [noteToPayer, setNoteToPayer] = useState('DropBack 14-day price protection difference refund')
  const [loading, setLoading] = useState(true)
  const [executing, setExecuting] = useState(false)
  const [response, setResponse] = useState<any | null>(null)
  const [latency, setLatency] = useState<number | null>(null)
  const [error, setError] = useState('')

  const loadPageData = async () => {
    setLoading(true)
    try {
      const [status, orders] = await Promise.all([
        getApimaticStatus(),
        api<SandboxOrder[]>('/apimatic/sandbox-orders').catch(() => [] as SandboxOrder[]),
      ])
      setManifest(status)
      setSandboxOrders(orders)
      const latest = orders.find(order => order.order_id)
      if (latest) {
        setOrderId(current => current || latest.order_id)
        setCaptureId(current => current || latest.capture_id || '')
      }
    } catch (err) {
      toast?.({ kind: 'error', message: err instanceof Error ? err.message : 'Could not load the PayPal API lab.' })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadPageData().then(async () => {
      const started = performance.now()
      try {
        const health = await invokeApimaticTool('paypal_check_sandbox_health', {})
        setResponse(health)
        setLatency(Math.round(performance.now() - started))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'PayPal sandbox health check failed.')
      }
    })
  }, [])

  const handleRunTool = async () => {
    setError('')
    if (selectedTool === 'paypal_get_order_details' && !orderId.trim()) {
      setError('Choose a captured PayPal sandbox order first.')
      return
    }
    if ((selectedTool === 'paypal_get_capture_status' || selectedTool === 'paypal_issue_capture_refund') && !captureId.trim()) {
      setError('Choose a captured PayPal sandbox payment first.')
      return
    }
    if (selectedTool === 'paypal_issue_capture_refund') {
      const amount = Number(refundAmount)
      if (!Number.isFinite(amount) || amount <= 0) {
        setError('Enter a refund amount greater than zero.')
        return
      }
      if (!window.confirm(`Issue a ${new Intl.NumberFormat('en-US', { style: 'currency', currency: refundCurrency }).format(amount)} refund to PayPal capture ${captureId}?`)) return
    }

    setExecuting(true)
    setResponse(null)
    setLatency(null)
    let args: Record<string, any> = {}
    if (selectedTool === 'paypal_get_order_details') args = { order_id: orderId.trim() }
    if (selectedTool === 'paypal_get_capture_status') args = { capture_id: captureId.trim() }
    if (selectedTool === 'paypal_issue_capture_refund') {
      args = { capture_id: captureId.trim(), amount: Number(refundAmount), currency: refundCurrency, note_to_payer: noteToPayer }
    }
    const started = performance.now()
    try {
      const result = await invokeApimaticTool(selectedTool, args)
      setResponse(result)
      setLatency(Math.round(performance.now() - started))
      if (result.status === 'SUCCESS') toast?.({ kind: 'success', message: `${selectedTool} completed.` })
      else setError(result.error || 'PayPal did not complete the request.')
    } catch (err) {
      setLatency(Math.round(performance.now() - started))
      setError(err instanceof Error ? err.message : 'Tool execution failed.')
    } finally {
      setExecuting(false)
    }
  }

  const selected = TOOLS.find(tool => tool.name === selectedTool) || TOOLS[0]
  const contracts = Object.entries(manifest?.schemas || {})

  return (
    <div className="api-lab-page" data-testid="apimatic-page">
      <div className="page-heading api-lab-heading">
        <div>
          <div className="eyebrow">APIMATIC CONTEXT PLUGIN <span>·</span> PAYPAL SANDBOX</div>
          <h1>PayPal API lab</h1>
          <p>Inspect the APIMatic PayPal contract manifest and run DropBack’s server-side bridge against PayPal Sandbox.</p>
        </div>
        <button type="button" className="button button-light" onClick={() => void loadPageData()} disabled={loading}>
          {loading ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />} Refresh
        </button>
      </div>

      <section className="api-connection-strip">
        <div className="api-connection-mark"><Code2 size={18} /></div>
        <div className="api-connection-copy">
          <b>{manifest?.context_plugin_name || 'PayPal Orders & Payments context'}</b>
          <span>Manifest v{manifest?.version || '—'} · Orders v2 + Payments v2 · {manifest?.tools_count ?? 4} MCP tools · {manifest?.manifest_loaded ? 'loaded from repository' : 'manifest unavailable'}</span>
        </div>
        <div className={`api-health-chip ${manifest?.sandbox_ready ? 'ready' : 'missing'}`}>
          <i /> PayPal {manifest?.environment || 'sandbox'} {manifest?.sandbox_ready ? 'credentials configured' : 'credentials needed'}
        </div>
        <a href="https://apimatic.io" target="_blank" rel="noreferrer" className="api-external-link">APIMatic <ExternalLink size={13} /></a>
      </section>

      {!manifest?.sandbox_ready && (
        <div className="api-credentials-note"><ShieldCheck size={15} /><span>Set PayPal sandbox client credentials on the backend. They stay server-side and are never shown in this page.</span></div>
      )}

      <div className="api-lab-grid">
        <section className="api-contract-panel">
          <div className="api-panel-heading"><div><span>CONTEXT MANIFEST</span><h2>PayPal contracts</h2></div><span className="manifest-file">.context-plugins/paypal.json</span></div>
          <p className="api-panel-copy">The APIMatic Context Plugin manifest is the source for these routes and request fields. DropBack’s backend bridge sends the corresponding requests to PayPal Sandbox; the merchant claim flow refunds only after approval.</p>
          <div className="api-contract-list">
            {contracts.map(([name, contract]) => (
              <div className="api-contract-row" key={name}>
                <span className={`api-method method-${String(contract.method || 'get').toLowerCase()}`}>{contract.method}</span>
                <div><b>{name.replaceAll('_', ' ')}</b><code>{contract.path}</code></div>
                <Check size={15} />
              </div>
            ))}
            {!contracts.length && <div className="api-empty">Loading the manifest…</div>}
          </div>
          <div className="api-credential-foot"><ShieldCheck size={15} /><span>OAuth credentials are loaded by the backend. No keys are exposed to the browser.</span></div>
        </section>

        <section className="api-runner-panel">
          <div className="api-panel-heading"><div><span>MCP TOOL RUNNER</span><h2>Make a sandbox call</h2></div><span className="api-live-tag"><i /> SANDBOX</span></div>
          <div className="api-tool-list">
            {TOOLS.map(tool => (
              <button key={tool.name} type="button" className={`api-tool-option ${selectedTool === tool.name ? 'selected' : ''}`} onClick={() => { setSelectedTool(tool.name); setError('') }}>
                <span><b>{tool.label}</b><small>{tool.description}</small></span>
                {selectedTool === tool.name && <Check size={15} />}
              </button>
            ))}
          </div>

          {sandboxOrders.length > 0 && (selected.kind === 'order' || selected.kind === 'capture' || selected.kind === 'refund') && (
            <label className="api-field">Use a recent sandbox order
              <select className="mcp-tool-select" value={sandboxOrders.find(order => order.order_id === orderId)?.order_id || ''} onChange={event => {
                const order = sandboxOrders.find(item => item.order_id === event.target.value)
                if (order) { setOrderId(order.order_id); setCaptureId(order.capture_id || '') }
              }}>
                <option value="">Choose an order</option>
                {sandboxOrders.map(order => <option key={order.order_id} value={order.order_id}>{order.buyer_name || 'Buyer'} · {order.item_name} · {order.order_id}</option>)}
              </select>
            </label>
          )}

          {selected.kind === 'order' && <label className="api-field">PayPal order ID<input value={orderId} onChange={event => setOrderId(event.target.value)} placeholder="Order ID from a sandbox checkout" /></label>}
          {(selected.kind === 'capture' || selected.kind === 'refund') && <label className="api-field">PayPal capture ID<input value={captureId} onChange={event => setCaptureId(event.target.value)} placeholder="Capture ID from a completed sandbox payment" /></label>}
          {selected.kind === 'refund' && <div className="api-refund-fields">
            <label className="api-field">Refund amount<input type="number" min="0.01" step="0.01" value={refundAmount} onChange={event => setRefundAmount(event.target.value)} placeholder="Enter amount to refund" /></label>
            <label className="api-field">Currency<input value={refundCurrency} onChange={event => setRefundCurrency(event.target.value.toUpperCase())} maxLength={3} /></label>
            <label className="api-field api-note-field">Note to payer<input value={noteToPayer} onChange={event => setNoteToPayer(event.target.value)} maxLength={255} /></label>
            <div className="api-refund-warning"><AlertCircle size={14} /> This sends a real refund in your PayPal sandbox account.</div>
          </div>}

          {sandboxOrders.length === 0 && selected.kind !== 'health' && <div className="api-empty-order">No PayPal sandbox orders yet. Complete a sandbox checkout to load real order and capture IDs here.</div>}
          {error && <div className="api-error"><AlertCircle size={15} />{error}</div>}
          <div className="api-run-actions">
            <button type="button" className="button button-dark" onClick={handleRunTool} disabled={executing || loading} data-testid="mcp-execute-btn">
              {executing ? <><LoaderCircle size={15} className="spin" /> Running…</> : <><Play size={14} /> {selected.kind === 'refund' ? 'Issue sandbox refund' : 'Run tool'}</>}
            </button>
            {latency !== null && <span>{latency} ms</span>}
          </div>
          <div className="api-response-wrap" data-testid="mcp-response">
            <div className="api-response-head"><b>Response</b>{response?.status && <span className={`api-response-status ${response.status === 'SUCCESS' ? 'ok' : 'bad'}`}>{response.status}</span>}</div>
            {response ? <pre className="json-viewer">{JSON.stringify(response, null, 2)}</pre> : <div className="api-response-empty">Run a tool to inspect its response payload.</div>}
          </div>
        </section>
      </div>
    </div>
  )
}
