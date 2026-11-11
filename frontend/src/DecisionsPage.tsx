import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import type { ColDef } from 'ag-grid-community'
import {
  ArrowRight, Brain, Check, ExternalLink, FileText, LoaderCircle, LockKeyhole,
  MessageSquare, RefreshCw, Search, ShieldCheck, Sparkles, UserRound, WalletCards, X,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { getDecisions, money, resolveClaim } from './api'
import type { Decision } from './types'

const GridTable = lazy(() => import('./GridTable'))

export default function DecisionsPage({
  toast,
}: {
  toast: (t: { message: string; kind: 'success' | 'error' | 'info' }) => void
}) {
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [loading, setLoading] = useState(false)
  const [working, setWorking] = useState('')
  const [quick, setQuick] = useState('')
  const [inspecting, setInspecting] = useState<Decision | null>(null)
  const [compactGrid, setCompactGrid] = useState(() => window.matchMedia('(max-width: 760px)').matches)

  const refresh = async () => {
    setLoading(true)
    try {
      const data = await getDecisions()
      setDecisions(data)
    } catch {
      toast({ kind: 'error', message: 'Could not load claims & decisions.' })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  useEffect(() => {
    const media = window.matchMedia('(max-width: 760px)')
    const sync = () => setCompactGrid(media.matches)
    sync()
    media.addEventListener('change', sync)
    return () => media.removeEventListener('change', sync)
  }, [])

  const handleAction = async (
    row: Decision,
    kind: 'approve' | 'reject',
    refundAmount?: number,
    customMessage?: string
  ) => {
    setWorking(row.id)
    try {
      const result = await resolveClaim(row.id, {
        action: kind,
        refund_amount: refundAmount,
        custom_message: customMessage,
      })
      if (kind === 'approve') {
        toast({
          kind: 'success',
          message: result.settlement_mode === 'demo_ledger'
            ? `Demo case approved. ${money(result.refund_amount, result.currency)} recorded locally; no money was moved.`
            : `Claim approved. ${money(result.refund_amount, result.currency)} refund status: ${result.refund_status || 'processing'}.`,
        })
      } else {
        toast({ kind: 'info', message: 'Claim rejected.' })
      }
      await refresh()
    } catch (err: any) {
      toast({ kind: 'error', message: err?.message || 'Action failed.' })
    } finally {
      setWorking('')
    }
  }

  const columns = useMemo<ColDef<Decision>[]>(
    () => [
      {
        field: 'buyer_name',
        headerName: 'BUYER',
        flex: compactGrid ? 0.95 : 1.05,
        minWidth: compactGrid ? 104 : 175,
        cellRenderer: (p: { data: Decision }) => {
          const initials = (p.data.buyer_name || 'Buyer')
            .split(' ')
            .map(n => n[0])
            .join('')
            .toUpperCase()
            .slice(0, 2)
          const orderNum = p.data.paypal_order_id ? `Order ${p.data.paypal_order_id.slice(-8).toUpperCase()}` : `Order ${p.data.order_id.slice(0, 8).toUpperCase()}`
          return (
            <div className="claim-buyer-cell">
              <div className="grid-buyer-avatar">{initials}</div>
              <div className="grid-buyer">
                <b>{p.data.buyer_name || 'Buyer'}</b>
                <span>{orderNum}</span>
              </div>
            </div>
          )
        },
      },
      {
        field: 'product_name',
        headerName: 'PRODUCT',
        flex: compactGrid ? 1.05 : 1.2,
        minWidth: compactGrid ? 108 : 190,
        cellRenderer: (p: { data: Decision }) => (
          <div className="claim-product-cell">
            <b>{p.data.product_name}</b>
            <span>{p.data.sku}</span>
          </div>
        ),
      },
      {
        field: 'competitor_name',
        headerName: 'MARKET PRICE',
        flex: compactGrid ? 1 : 1.1,
        minWidth: compactGrid ? 100 : 165,
        cellRenderer: (p: { data: Decision }) => {
          const compPrice = p.data.competitor_price
          const dropDelta = (p.data.purchase_price || 0) - (compPrice || p.data.purchase_price || 0)
          return (
            <div className="claim-market-cell">
              {compPrice ? (
                <div className="claim-market-price" data-testid="channel3-evidence">
                  <span className={p.data.evidence_source === 'demo_offer_fixture' ? 'demo-evidence-dot' : 'c3-live-dot'} title={p.data.evidence_source === 'demo_offer_fixture' ? 'Saved demo offer' : 'Live Channel3 price signal'} />
                  <b>{money(compPrice, p.data.currency)}</b>
                </div>
              ) : (
                <span style={{ fontSize: 11, color: '#94a3b8' }}>—</span>
              )}
              {dropDelta > 0 && (
                <span className="claim-market-detail">
                  {p.data.competitor_name || 'Retailer'} · {money(dropDelta, p.data.currency)} below paid
                </span>
              )}
            </div>
          )
        },
      },
      {
        field: 'return_probability',
        headerName: 'RETURN RISK',
        flex: 0.9,
        minWidth: 138,
        hide: compactGrid,
        cellRenderer: (p: { value: number }) => <RiskBar probability={p.value || 0} />,
      },
      {
        headerName: 'RETURN VS. SETTLE',
        flex: compactGrid ? 1.05 : 1.15,
        minWidth: compactGrid ? 112 : 176,
        cellRenderer: (p: { data: Decision }) => {
          const returnLoss = p.data.estimated_return_cost || 0
          const diffSettle = p.data.refund_amount || 0
          const netSaved = p.data.estimated_savings || 0
          return (
            <div className="claim-cost-cell">
              <span><small>Return</small><b>{money(returnLoss, p.data.currency)}</b></span>
              <span><small>Settle</small><b>{money(diffSettle, p.data.currency)}</b></span>
              <strong>+{money(netSaved, p.data.currency)} saved</strong>
            </div>
          )
        },
      },
      {
        field: 'status',
        headerName: 'STATUS',
        flex: 0.8,
        minWidth: 112,
        hide: compactGrid,
        cellRenderer: (p: { value: string }) => (
          <span className={`decision-status ${p.value.toLowerCase().replace('_', '-')}`}>
            {p.value.replace('_', ' ')}
          </span>
        ),
      },
      {
        headerName: 'REVIEW',
        flex: compactGrid ? 0.9 : 0.85,
        minWidth: compactGrid ? 104 : 136,
        sortable: false,
        cellRenderer: (p: { data: Decision }) => {
          if (p.data.status === 'PENDING_REVIEW') {
            return (
              <button
                type="button"
                className="grid-settle-btn"
                data-testid="settle-btn"
                onClick={() => setInspecting(p.data)}
                title="Review the buyer claim, costs, evidence, and draft resolution"
              >
                <FileText size={14} /> Review case
              </button>
            )
          }
          if (p.data.status === 'APPROVED') {
            return <Link className="buyer-outcome-link" to={`/portal/${encodeURIComponent(p.data.order_id)}`} target="_blank">
              <span className="decision-status approved">{p.data.settlement_mode === 'demo_ledger' ? 'DEMO APPROVED' : 'REFUNDED'}</span><ExternalLink size={13} />
            </Link>
          }
          return <span className="grid-muted">{p.data.status}</span>
        },
      },
    ],
    [compactGrid]
  )

  const historyColumns = useMemo<ColDef<Decision>[]>(() => [
    {
      field: 'buyer_name', headerName: 'BUYER & ORDER', flex: 1, minWidth: compactGrid ? 108 : 170,
      cellRenderer: (p: { data: Decision }) => {
        const initials = (p.data.buyer_name || 'Buyer').split(' ').map(name => name[0]).join('').toUpperCase().slice(0, 2)
        return <div className="claim-buyer-cell"><div className="grid-buyer-avatar">{initials}</div><div className="grid-buyer"><b>{p.data.buyer_name || 'Buyer'}</b><span>{p.data.paypal_order_id ? `PayPal ${p.data.paypal_order_id.slice(-7)}` : `Order ${p.data.order_id.slice(0, 7)}`}</span></div></div>
      },
    },
    {
      field: 'product_name', headerName: 'PRODUCT', flex: 1.15, minWidth: compactGrid ? 126 : 190,
      cellRenderer: (p: { data: Decision }) => <div className="claim-product-cell"><b>{p.data.product_name}</b><span>{p.data.sku}</span></div>,
    },
    {
      field: 'competitor_price', headerName: 'CHANNEL3 OFFER', flex: 1, minWidth: compactGrid ? 125 : 180,
      cellRenderer: (p: { data: Decision }) => <div className="claim-market-cell"><div className="claim-market-price"><span className={p.data.evidence_source === 'demo_offer_fixture' ? 'demo-evidence-dot' : 'c3-live-dot'} /><b>{money(p.data.competitor_price || 0, p.data.currency)}</b></div><span className="claim-market-detail">{p.data.competitor_name || 'Matched retailer'} · {money(Math.max(0, (p.data.purchase_price || 0) - (p.data.competitor_price || 0)), p.data.currency)} below paid</span></div>,
    },
    {
      headerName: 'RETURN VS SETTLE', flex: 1, minWidth: 168, hide: compactGrid,
      cellRenderer: (p: { data: Decision }) => <div className="claim-cost-cell"><span><small>Return</small><b>{money(p.data.estimated_return_cost || 0, p.data.currency)}</b></span><span><small>Settle</small><b>{money(p.data.refund_amount || 0, p.data.currency)}</b></span><strong>+{money(p.data.estimated_savings || 0, p.data.currency)} saved</strong></div>,
    },
    {
      field: 'status', headerName: 'RESOLUTION', flex: .85, minWidth: compactGrid ? 118 : 150,
      cellRenderer: (p: { data: Decision }) => <div className="history-resolution-cell"><span className={`decision-status ${p.data.status.toLowerCase().replace('_', '-')}`}>{p.data.status === 'REFUNDED' ? 'REFUNDED' : p.data.status.replaceAll('_', ' ')}</span>{p.data.refund_status && <small>{p.data.settlement_mode === 'paypal_sandbox' ? `PayPal · ${p.data.refund_status.toLowerCase()}` : p.data.refund_status}</small>}<button type="button" data-testid="view-history-case" className="history-report-link" onClick={() => setInspecting(p.data)}>View case report</button></div>,
    },
  ], [compactGrid])

  const awaiting = decisions.filter(row => row.status === 'PENDING_REVIEW')
  const resolved = decisions.filter(row => row.status !== 'PENDING_REVIEW')
  const totalSaved = resolved
    .filter(row => row.status === 'APPROVED' || row.status === 'REFUNDED')
    .reduce((sum, row) => sum + (row.estimated_savings || 0), 0)

  return (
    <>
      <div className="page-heading claims-heading" data-testid="claims-page">
        <div>
          <div className="eyebrow">BUYER CLAIMS <span>·</span> MERCHANT REVIEW</div>
          <h1>Price protection claims</h1>
          <p>
            A buyer found a lower price. Review the evidence and return costs, then choose how to resolve the case.
          </p>
        </div>
        <div className="heading-actions">
          <button type="button" className="button button-light" onClick={refresh} disabled={loading}>
            <RefreshCw size={15} /> Refresh Decisions
          </button>
        </div>
      </div>

      <div className="review-banner" data-testid="claims-banner">
        <div className="review-banner-icon"><ShieldCheck size={18} /></div>
        <div>
          <b>{awaiting.length ? 'Customer request received' : 'Buyer-first review flow'}</b>
          <span>
            {awaiting.length
              ? 'This claim came from the customer portal. Review the case before approving any settlement.'
              : 'Open the local /demo/run URL to launch the complete Sandbox buyer journey.'}
          </span>
        </div>
        <div className="review-banner-count">
          <b>{awaiting.length}</b>
          <span>awaiting review</span>
        </div>
      </div>

      <section className="section-block grid-section">
        <div className="section-head">
          <div>
            <div className="section-title">
              Awaiting your review <span className="count-bubble">{awaiting.length}</span>
            </div>
            <p>
              Buyer note, verified market price, and the estimated cost of a physical return are together in AG Grid.
            </p>
          </div>
          <div className="grid-tools">
            <div className="search-field">
              <Search size={15} />
              <input
                value={quick}
                placeholder="Search by buyer, SKU, retailer, or status…"
                onChange={e => setQuick(e.target.value)}
              />
            </div>
          </div>
        </div>

        {awaiting.length ? (
          <div className="table-frame">
            <div className={`ag-theme-quartz grid-wrap decision-grid${compactGrid ? ' decision-grid-compact' : ''}`} data-testid="claims-grid">
              <Suspense fallback={<div className="grid-loading">Loading AG Grid table…</div>}>
                <GridTable
                  rowData={awaiting}
                  columnDefs={columns}
                  quickFilterText={quick}
                  pagination
                  paginationPageSize={10}
                  rowHeight={compactGrid ? 82 : 72}
                />
              </Suspense>
            </div>
          </div>
        ) : (
          <div className="claim-empty-state">
              <div className="claim-empty-icon"><UserRound size={20} /></div>
              <div>
                <b>No buyer claims yet</b>
                <p>The complete local Sandbox walkthrough starts at <code>/demo/run</code>. Buyer requests appear here for review.</p>
              </div>
          </div>
        )}
      </section>

      {resolved.length > 0 && (
        <section className="section-block grid-section">
          <div className="section-head">
            <div>
              <div className="section-title">
                Previous decisions <span className="count-bubble">{resolved.length}</span>
              </div>
              <p>
                Estimated margin preserved across approved cases: <b>{money(totalSaved)}</b>.
              </p>
            </div>
          </div>
          <div className="table-frame">
            <div className={`ag-theme-quartz grid-wrap history-grid${compactGrid ? ' history-grid-compact' : ''}`}>
              <Suspense fallback={<div className="grid-loading">Loading history table…</div>}>
                <GridTable
                  rowData={resolved}
                  columnDefs={historyColumns}
                  pagination
                  paginationPageSize={10}
                  domLayout="autoHeight"
                  rowHeight={78}
                />
              </Suspense>
            </div>
          </div>
        </section>
      )}

      <div className="claims-integration-note">
        <ShieldCheck size={16} />
        <span>Merchant approval controls each settlement. PayPal sandbox refunds run only for captured sandbox orders.</span>
        <Link to="/apimatic">PayPal API details <ArrowRight size={14} /></Link>
      </div>

      {inspecting && (
        <DecisionAnalysisModal
          decision={inspecting}
          onClose={() => setInspecting(null)}
          onAction={handleAction}
          working={working}
        />
      )}
    </>
  )
}

function RiskBar({ probability }: { probability: number }) {
  const percent = Math.round(probability * 100)
  const color = percent >= 70 ? '#dc2626' : percent >= 40 ? '#f59e0b' : '#10b981'
  const label = percent >= 70 ? 'HIGH' : percent >= 40 ? 'MED' : 'LOW'
  return (
    <div className="risk-bar-wrap" data-testid="risk-gauge">
      <div className="risk-bar">
        <i style={{ width: `${percent}%`, background: color }} />
      </div>
      <span style={{ fontWeight: 700, color, minWidth: 32 }}>{percent}%</span>
      <span style={{
        fontSize: 8, fontWeight: 800, letterSpacing: '0.06em',
        padding: '2px 5px', borderRadius: 3,
        background: percent >= 70 ? '#fbe9e7' : percent >= 40 ? '#fef3e5' : '#e8f4ec',
        color,
      }}>{label}</span>
    </div>
  )
}

export function DecisionAnalysisModal({
  decision,
  onClose,
  onAction,
  working,
}: {
  decision: Decision | null
  onClose: () => void
  onAction: (row: Decision, kind: 'approve' | 'reject', refundAmount?: number, customMessage?: string) => Promise<void>
  working: string
}) {
  if (!decision) return null

  const report = decision.analysis_report
  const probPercent = Math.round((decision.return_probability || 0) * 100)
  const isAi = report?.provider === 'openai' || report?.provider === 'gemini'
  const providerLabel = report?.provider === 'openai'
    ? 'OpenAI (gpt-4.1-mini)'
    : report?.provider === 'gemini'
    ? 'Google Gemini 2.0'
    : 'Actuarial Deterministic Engine'

  const fin = report?.financial_breakdown
  const returnCost = fin?.estimated_return_cost ?? decision.estimated_return_cost
  const refundAmt = fin?.proposed_refund ?? decision.refund_amount
  const netSavings = fin?.net_savings ?? decision.estimated_savings
  const evidenceLabel = decision.evidence_source === 'demo_offer_fixture' ? 'Saved demo offer' : 'Live Channel3 offer'
  const demoSettlement = decision.settlement_mode === 'demo_ledger'
  const demoDraft = `Hi ${decision.buyer_name || 'there'}, thank you for reaching out under our 14-day price guarantee. We’ve recorded a demo settlement of ${money(refundAmt, decision.currency)} in the local prototype. No PayPal refund was sent and no funds moved.`
  const paypalDraft = `Hi ${decision.buyer_name || 'there'}, thank you for shopping with us! We appreciate you reaching out under our 14-day price guarantee. We've credited ${money(refundAmt, decision.currency)} directly to your PayPal account to match the competitor price, so you can keep enjoying your purchase without returning it.`

  const [settleAmount, setSettleAmount] = useState(String(refundAmt))
  const [draftedMessage, setDraftedMessage] = useState(
    decision.merchant_message || (demoSettlement
      ? demoDraft
      : decision.ai_drafted_message || report?.drafted_customer_message || paypalDraft)
  )

  return (
    <div className="analysis-modal-overlay" data-testid="claim-modal" onClick={onClose}>
      <div className="analysis-modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 760 }}>
        <div className="analysis-modal-header">
          <div>
            <div className="modal-eyebrow">
              <span className={`ai-badge ${isAi ? 'ai-live' : 'ai-rules'}`}>
                <Brain size={13} /> {providerLabel}
              </span>
              {decision.customer_claim && (
                <span className="customer-claim-pill"><i></i> CUSTOMER DISPUTE CLAIM</span>
              )}
              <span className={`decision-status ${decision.status.toLowerCase().replace('_', '-')}`}>
                {decision.status.replace('_', ' ')}
              </span>
            </div>
            <h2>AI Return-Risk & Price Protection Report</h2>
            <p className="modal-sub">
              Product: <b>{decision.product_name}</b> (SKU: {decision.sku}) · Buyer: <b>{decision.buyer_name || 'Buyer'}</b> ({decision.buyer_email || '—'})
            </p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        <div className="analysis-modal-body">
          {/* CHANNEL3 EVIDENCE BOX */}
          <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontSize: 10, fontWeight: 800, color: '#64748b', letterSpacing: '0.06em' }}>
                {evidenceLabel.toUpperCase()}
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                <b style={{ fontSize: 14, color: '#1e293b' }}>{decision.competitor_name || 'Authorized Retailer'}:</b>
                <span style={{ fontSize: 14, fontWeight: 800, color: '#047857' }}>
                  {money(decision.competitor_price || (decision.purchase_price - decision.refund_amount))}
                </span>
                <span style={{ fontSize: 12, color: '#64748b' }}>
                  (Buyer paid {money(decision.purchase_price)} · Delta: <b style={{ color: '#dc2626' }}>−{money(decision.refund_amount)}</b>)
                </span>
              </div>
            </div>
            {decision.evidence_source === 'demo_offer_fixture' && (
              <span style={{ fontSize: 11, background: '#fef3c7', color: '#92400e', padding: '3px 8px', borderRadius: 6, fontWeight: 700 }}>
                Demo fixture
              </span>
            )}
          </div>

          {/* CUSTOMER CLAIM NOTES CALLOUT */}
          {decision.customer_claim && decision.customer_notes && (
            <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 8, padding: 12 }}>
              <span style={{ fontSize: 10, fontWeight: 800, color: '#1e40af', display: 'flex', alignItems: 'center', gap: 5 }}>
                <MessageSquare size={13} /> BUYER CLAIM NOTES & RETURN REASON
              </span>
              <p style={{ margin: '6px 0 0', fontSize: 12, color: '#1e293b', fontStyle: 'italic', lineHeight: 1.5 }}>
                "{decision.customer_notes}"
              </p>
            </div>
          )}

          <div className="modal-metrics-grid">
            <div className="modal-metric-card">
              <span className="card-label">RETURN PROBABILITY</span>
              <div className="metric-score">
                <span className="score-num">{probPercent}%</span>
                <span className={`risk-pill risk-${(report?.risk_level || 'HIGH').toLowerCase()}`}>
                  {report?.risk_level || 'HIGH'} RISK
                </span>
              </div>
              <div className="modal-risk-bar"><i style={{ width: `${probPercent}%` }} /></div>
              <span className="card-hint">Confidence: <b>{report?.confidence || 'HIGH'}</b></span>
            </div>

            <div className="modal-metric-card">
              <span className="card-label">RECOMMENDED DIFFERENCE REFUND</span>
              <div className="metric-score">
                <span className="score-num refund-num">{money(refundAmt, decision.currency)}</span>
              </div>
              <span className="card-hint">{demoSettlement ? 'Recorded locally in the demo ledger' : 'PayPal capture refund after approval'}</span>
            </div>

            <div className="modal-metric-card highlight-card">
              <span className="card-label">MERCHANT MARGIN PROTECTED</span>
              <div className="metric-score">
                <span className="score-num savings-num">+{money(netSavings, decision.currency)}</span>
              </div>
              <span className="card-hint">Net saved compared to physical return logistics</span>
            </div>
          </div>

          {/* SIDE BY SIDE FINANCIAL COSTING */}
          <div className="modal-section">
            <h3><WalletCards size={16} /> Cost of Physical Return vs Proactive Difference Settlement</h3>
            <div className="financial-comparison-grid">
              <div className="fin-col return-col">
                <div className="fin-col-title">COST OF FULL PHYSICAL RETURN</div>
                <div className="fin-row"><span>Reverse shipping estimate</span><b>{money(fin?.reverse_shipping ?? 24, decision.currency)}</b></div>
                <div className="fin-row"><span>Restocking & inspection</span><b>{money(fin?.restocking_cost ?? (decision.purchase_price || 0) * 0.15, decision.currency)}</b></div>
                <div className="fin-row"><span>Open-box markdown</span><b>{money(fin?.open_box_loss ?? (decision.purchase_price || 0) * 0.25, decision.currency)}</b></div>
                <div className="fin-total-row"><span>Total Physical Return Loss</span><b>{money(returnCost, decision.currency)}</b></div>
              </div>

              <div className="fin-col refund-col">
                <div className="fin-col-title">PROACTIVE DIFFERENCE SETTLEMENT</div>
                <div className="fin-row"><span>Direct Price Delta Credit</span><b>{money(refundAmt, decision.currency)}</b></div>
                <div className="fin-row"><span>Customer Keeps Item (No Freight)</span><b>$0.00 Freight</b></div>
                <div className="fin-row"><span>No Warehouse Restocking</span><b>$0.00 Restock</b></div>
                <div className="fin-total-row highlight-row"><span>Net Merchant Margin Saved</span><b>+{money(netSavings, decision.currency)}</b></div>
              </div>
            </div>
          </div>

          {/* AI NARRATIVE & DRIVERS */}
          <div className="modal-section narrative-section">
            <h3><Brain size={16} /> AI Executive Summary</h3>
            <blockquote className="modal-quote">
              <p>{decision.reasoning}</p>
            </blockquote>
            {report?.key_drivers && report.key_drivers.length > 0 && (
              <ul className="key-drivers-list" data-testid="key-drivers">
                {report.key_drivers.map((driver: string, i: number) => (
                  <li key={i}>{driver}</li>
                ))}
              </ul>
            )}
          </div>

          {/* EDITABLE DRAFTED CUSTOMER RESOLUTION MESSAGE */}
          <div className="modal-section">
            <div className="drafted-message-wrap">
              <div className="drafted-message-header">
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Sparkles size={14} color="#059669" /> AI-Drafted Customer Resolution Message
                </span>
                <span style={{ fontSize: 10, color: '#64748b' }}>Merchant can customize before sending</span>
              </div>
              <textarea
                className="drafted-message-area"
                value={draftedMessage}
                onChange={e => setDraftedMessage(e.target.value)}
                placeholder="Draft message for buyer…"
              />
            </div>
          </div>

          {/* SETTLEMENT AMOUNT ADJUSTMENT */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#f8fafc', padding: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}>
            <div>
              <b style={{ fontSize: 12, color: '#1e293b' }}>{demoSettlement ? 'Demo settlement amount:' : 'PayPal refund amount:'}</b>
              <p style={{ margin: '2px 0 0', fontSize: 11, color: '#64748b' }}>
                {demoSettlement ? 'This sample order records a local demo credit; no money moves.' : 'A refund is sent to the buyer’s PayPal account after approval.'}
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 14, fontWeight: 700 }}>$</span>
              <input
                type="number"
                step="0.01"
                style={{ width: 90, height: 36, border: '1px solid #cbd5e1', borderRadius: 6, padding: '0 8px', fontSize: 14, fontWeight: 700 }}
                value={settleAmount}
                onChange={e => setSettleAmount(e.target.value)}
              />
            </div>
          </div>
        </div>

        <div className="analysis-modal-footer">
          <div className="footer-note">
            <LockKeyhole size={14} />
            <span>{demoSettlement ? 'Sample order: approval updates the local demo ledger only.' : 'Merchant approval is required before the PayPal refund is sent.'}</span>
          </div>
          <div className="footer-actions">
            <button type="button" className="button button-light" onClick={onClose}>
              Cancel
            </button>
            {decision.status === 'PENDING_REVIEW' && (
              <>
                <button
                  type="button"
                  className="reject-button button"
                  data-testid="reject-btn"
                  disabled={working === decision.id}
                  onClick={async () => {
                    await onAction(decision, 'reject', undefined, draftedMessage)
                    onClose()
                  }}
                >
                  Reject Claim
                </button>
                <button
                  type="button"
                  className="approve-button button"
                  data-testid="approve-refund-btn"
                  disabled={working === decision.id}
                  onClick={async () => {
                    await onAction(decision, 'approve', Number(settleAmount), draftedMessage)
                    onClose()
                  }}
                >
                  {working === decision.id ? (
                    <><LoaderCircle size={15} className="spin" /> Processing…</>
                  ) : (
                    <><Check size={15} /> {demoSettlement ? 'Approve demo settlement' : 'Approve & issue PayPal refund'}</>
                  )}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
