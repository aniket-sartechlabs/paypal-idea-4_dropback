import { useEffect, useState } from 'react'
import { AlertCircle, Check, Code2, ExternalLink, LoaderCircle, Play, Plug, RefreshCw, ShieldCheck } from 'lucide-react'
import { api, getPayPalToolsStatus, invokePayPalTool, money } from './api'
import type { PayPalToolsStatus } from './types'

type SandboxOrder = {
  order_id: string
  capture_id: string | null
  buyer_name: string
  item_name: string
  amount: number
  currency: string
  status: string
  refundable_balance: number
}

const TOOL_UI: Record<string, { label: string; kind: 'health' | 'order' | 'capture' | 'refund' }> = {
  paypal_check_sandbox_health: { label: 'Check sandbox health', kind: 'health' },
  paypal_get_order_details: { label: 'Get order details', kind: 'order' },
  paypal_get_capture_status: { label: 'Get capture status', kind: 'capture' },
  paypal_issue_capture_refund: { label: 'Issue capture refund', kind: 'refund' },
}

const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`)

export default function APIMaticPage({ toast }: { toast?: (t: { message: string; kind: 'success' | 'error' | 'info' }) => void }) {
  const [status, setStatus] = useState<PayPalToolsStatus | null>(null)
  const [sandboxOrders, setSandboxOrders] = useState<SandboxOrder[]>([])
  const [selectedTool, setSelectedTool] = useState('paypal_check_sandbox_health')
  const [orderId, setOrderId] = useState('')
  const [captureId, setCaptureId] = useState('')
  const [refundAmount, setRefundAmount] = useState('')
  const [noteToPayer, setNoteToPayer] = useState('DropBack price protection difference refund')
  // One key per refund the merchant intends to send; a retry of the same refund reuses it.
  const [refundKey, setRefundKey] = useState(newKey)
  const [loading, setLoading] = useState(true)
  const [executing, setExecuting] = useState(false)
  const [response, setResponse] = useState<any | null>(null)
  const [latency, setLatency] = useState<number | null>(null)
  const [error, setError] = useState('')

  const loadPageData = async () => {
    setLoading(true)
    try {
      const [toolStatus, orders] = await Promise.all([
        getPayPalToolsStatus(),
        api<SandboxOrder[]>('/paypal-tools/sandbox-orders').catch(() => [] as SandboxOrder[]),
      ])
      setStatus(toolStatus)
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
        setResponse(await invokePayPalTool('paypal_check_sandbox_health', {}))
        setLatency(Math.round(performance.now() - started))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'PayPal sandbox health check failed.')
      }
    })
  }, [])

  const selectTool = (name: string) => { setSelectedTool(name); setError('') }
  const kind = TOOL_UI[selectedTool]?.kind || 'health'

  const handleRunTool = async () => {
    setError('')
    if (kind === 'order' && !orderId.trim()) return setError('Choose a captured PayPal sandbox order first.')
    if ((kind === 'capture' || kind === 'refund') && !captureId.trim()) return setError('Choose a captured PayPal sandbox payment first.')
    let args: Record<string, any> = {}
    if (kind === 'order') args = { order_id: orderId.trim() }
    if (kind === 'capture') args = { capture_id: captureId.trim() }
    if (kind === 'refund') {
      const amount = Number(refundAmount)
      if (!Number.isFinite(amount) || amount <= 0) return setError('Enter a refund amount greater than zero.')
      if (!window.confirm(`Issue a ${money(amount)} refund to PayPal capture ${captureId}?`)) return
      args = { capture_id: captureId.trim(), amount: amount.toFixed(2), currency: 'USD', note_to_payer: noteToPayer }
    }

    setExecuting(true)
    setResponse(null)
    setLatency(null)
    const started = performance.now()
    try {
      const result = await invokePayPalTool(selectedTool, args, kind === 'refund' ? refundKey : undefined)
      setResponse(result)
      setLatency(Math.round(performance.now() - started))
      if (result.status === 'SUCCESS') {
        toast?.({ kind: 'success', message: kind === 'refund' ? `Refund ${result.refund_status?.toLowerCase() || 'sent'}${result.replayed ? ' (already sent)' : ''}.` : `${TOOL_UI[selectedTool]?.label} completed.` })
        if (kind === 'refund') { setRefundKey(newKey()); setRefundAmount(''); void loadPageData() }
      } else setError(result.error || 'PayPal did not complete the request.')
    } catch (err) {
      setLatency(Math.round(performance.now() - started))
      setError(err instanceof Error ? err.message : 'Tool execution failed.')
    } finally {
      setExecuting(false)
    }
  }

  const tools = status?.tools || []
  const selectedOrder = sandboxOrders.find(order => order.capture_id === captureId)

  return (
    <div className="api-lab-page" data-testid="apimatic-page">
      <div className="page-heading api-lab-heading">
        <div>
          <div className="eyebrow">PAYPAL SERVER SDK <span>·</span> GENERATED BY APIMATIC <span>·</span> MCP</div>
          <h1>PayPal API lab</h1>
          <p>Every PayPal call in DropBack goes through the APIMatic-generated PayPal Server SDK. Run those calls here, or connect an AI agent to DropBack’s MCP server.</p>
        </div>
        <button type="button" className="button button-light" onClick={() => void loadPageData()} disabled={loading}>
          {loading ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />} Refresh
        </button>
      </div>

      <section className="api-connection-strip">
        <div className="api-connection-mark"><Code2 size={18} /></div>
        <div className="api-connection-copy">
          <b>{status?.sdk_package || 'paypal-server-sdk'} {status?.sdk_version ? `v${status.sdk_version}` : ''}</b>
          <span>Orders v2 + Payments v2 · {status?.operations.length ?? 0} SDK operations · OAuth handled by the SDK</span>
        </div>
        <div className={`api-health-chip ${status?.sandbox_ready ? 'ready' : 'missing'}`}>
          <i /> PayPal {status?.environment || 'sandbox'} {status?.sandbox_ready ? 'credentials configured' : 'credentials needed'}
        </div>
        <a href="https://github.com/paypal/PayPal-Python-Server-SDK" target="_blank" rel="noreferrer" className="api-external-link">SDK <ExternalLink size={13} /></a>
      </section>

      {!status?.sandbox_ready && (
        <div className="api-credentials-note"><ShieldCheck size={15} /><span>Set PayPal sandbox client credentials on the backend. They stay server-side and are never shown in this page.</span></div>
      )}

      <div className="api-lab-grid">
        <section className="api-contract-panel">
          <div className="api-panel-heading"><div><span>PAYPAL SERVER SDK</span><h2>Operations DropBack uses</h2></div><span className="manifest-file">app/services/paypal.py</span></div>
          <p className="api-panel-copy">Requests are built with the SDK’s typed models (<code>OrderRequest</code>, <code>PurchaseUnitRequest</code>, <code>RefundRequest</code>, <code>Money</code>). Refunds send a <code>PayPal-Request-Id</code> so a retry can never pay twice.</p>
          <div className="api-contract-list">
            {(status?.operations || []).map(op => (
              <div className="api-contract-row" key={op.sdk_call} title={op.used_for}>
                <span className={`api-method method-${op.method.toLowerCase()}`}>{op.method}</span>
                <div><b style={{ textTransform: 'none', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>{op.sdk_call}</b><code>{op.path}</code></div>
                <Check size={15} />
              </div>
            ))}
            {!status && <div className="api-empty">Loading…</div>}
          </div>

          <div className="api-panel-heading" style={{ marginTop: 18 }}><div><span>MODEL CONTEXT PROTOCOL</span><h2>Connect an AI agent</h2></div><Plug size={16} /></div>
          <div className="api-contract-list">
            <div className="api-contract-row">
              <span className={`api-method ${status?.mcp.enabled ? 'method-get' : 'method-delete'}`}>{status?.mcp.enabled ? 'ON' : 'OFF'}</span>
              <div><b style={{ textTransform: 'none' }}>DropBack MCP server</b><code>{window.location.protocol}//{window.location.hostname}:8000{status?.mcp.path || '/mcp/'}</code></div>
            </div>
          </div>
          <p className="api-panel-copy" style={{ overflowWrap: 'anywhere' }}>
            {status?.mcp.enabled
              ? <>Read-only tools: {status.mcp.tools.join(', ')}. Clients send <code>{status.mcp.auth}</code>. Refunds stay a merchant click.</>
              : <>Set <code>MCP_API_TOKEN</code> in <code>.env</code> and restart the API to enable it.</>}
          </p>
          <div className="api-contract-list">
            <div className="api-contract-row">
              <span className={`api-method ${status?.apimatic_context_plugin.configured_in_repo ? 'method-get' : 'method-delete'}`}>DEV</span>
              <div><b style={{ textTransform: 'none' }}>APIMatic Context Plugin</b><code>{status?.apimatic_context_plugin.url}</code></div>
            </div>
          </div>
          <p className="api-panel-copy" style={{ overflowWrap: 'anywhere' }}>{status?.apimatic_context_plugin.purpose} Registered in the repo’s <code>.mcp.json</code>.</p>
        </section>

        <section className="api-runner-panel">
          <div className="api-panel-heading"><div><span>SDK TOOL RUNNER</span><h2>Make a sandbox call</h2></div><span className="api-live-tag"><i /> SANDBOX</span></div>
          <div className="api-tool-list">
            {tools.map(tool => (
              <button key={tool.name} type="button" className={`api-tool-option ${selectedTool === tool.name ? 'selected' : ''}`} onClick={() => selectTool(tool.name)}>
                <span><b>{TOOL_UI[tool.name]?.label || tool.name}</b><small>{tool.description}{tool.available_over_mcp ? ' · also on MCP' : ''}</small></span>
                {selectedTool === tool.name && <Check size={15} />}
              </button>
            ))}
          </div>

          {sandboxOrders.length > 0 && kind !== 'health' && (
            <label className="api-field">Use a recent sandbox order
              <select className="mcp-tool-select" value={sandboxOrders.find(order => order.order_id === orderId)?.order_id || ''} onChange={event => {
                const picked = sandboxOrders.find(item => item.order_id === event.target.value)
                if (picked) { setOrderId(picked.order_id); setCaptureId(picked.capture_id || '') }
              }}>
                <option value="">Choose an order</option>
                {sandboxOrders.map(order => <option key={order.order_id} value={order.order_id}>{order.buyer_name || 'Buyer'} · {order.item_name} · {order.order_id}</option>)}
              </select>
            </label>
          )}

          {kind === 'order' && <label className="api-field">PayPal order ID<input value={orderId} onChange={event => setOrderId(event.target.value)} placeholder="Order ID from a sandbox checkout" /></label>}
          {(kind === 'capture' || kind === 'refund') && <label className="api-field">PayPal capture ID<input value={captureId} onChange={event => setCaptureId(event.target.value)} placeholder="Capture ID from a completed sandbox payment" /></label>}
          {kind === 'refund' && <div className="api-refund-fields">
            <label className="api-field">Refund amount (USD){selectedOrder ? ` · up to ${money(selectedOrder.refundable_balance)}` : ''}<input type="number" min="0.01" step="0.01" value={refundAmount} onChange={event => setRefundAmount(event.target.value)} placeholder="Enter amount to refund" /></label>
            <label className="api-field api-note-field">Note to payer<input value={noteToPayer} onChange={event => setNoteToPayer(event.target.value)} maxLength={255} /></label>
            <div className="api-refund-warning"><AlertCircle size={14} /> This sends a real refund in your PayPal sandbox account. Each new refund gets its own idempotency key.</div>
          </div>}

          {sandboxOrders.length === 0 && kind !== 'health' && <div className="api-empty-order">No PayPal sandbox orders yet. Complete a sandbox checkout to load real order and capture IDs here.</div>}
          {error && <div className="api-error"><AlertCircle size={15} />{error}</div>}
          <div className="api-run-actions">
            <button type="button" className="button button-dark" onClick={handleRunTool} disabled={executing || loading} data-testid="mcp-execute-btn">
              {executing ? <><LoaderCircle size={15} className="spin" /> Running…</> : <><Play size={14} /> {kind === 'refund' ? 'Issue sandbox refund' : 'Run tool'}</>}
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
