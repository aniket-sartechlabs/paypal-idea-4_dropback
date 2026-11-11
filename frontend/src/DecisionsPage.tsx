import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import type { ColDef } from 'ag-grid-community'
import {
  Brain, Check,
  FileText, LoaderCircle, LockKeyhole, MessageSquare,
  RefreshCw, Search, Sparkles, WalletCards, X,
} from 'lucide-react'
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
          message: `Claim approved! ${money(result.refund_amount, result.currency)} refund credited to buyer via PayPal.`,
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
        headerName: 'BUYER & CLAIM',
        flex: 1.3,
        minWidth: 175,
        cellRenderer: (p: { data: Decision }) => {
          const initials = (p.data.buyer_name || 'Buyer')
            .split(' ')
            .map(n => n[0])
            .join('')
            .toUpperCase()
            .slice(0, 2)
          const orderNum = p.data.paypal_order_id ? `#${p.data.paypal_order_id.slice(-8)}` : `#${p.data.order_id.slice(0, 8)}`
          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div className="grid-buyer-avatar">{initials}</div>
              <div className="grid-buyer">
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <b>{p.data.buyer_name || 'Buyer'}</b>
                  {p.data.customer_claim ? (
                    <span className="customer-claim-pill"><i></i> CLAIM</span>
                  ) : (
                    <span className="customer-claim-pill auto-pill">AUTO</span>
                  )}
                </div>
                <span>{orderNum}</span>
              </div>
            </div>
          )
        },
      },
      {
        field: 'product_name',
        headerName: 'PRODUCT',
        flex: 1.2,
        minWidth: 160,
        cellRenderer: (p: { data: Decision }) => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <b style={{ fontSize: 12, color: '#1e293b' }}>{p.data.product_name}</b>
            <span style={{ fontSize: 10, color: '#64748b' }}>SKU: {p.data.sku}</span>
          </div>
        ),
      },
      {
        field: 'competitor_name',
        headerName: 'CHANNEL3 MARKET SIGNAL',
        flex: 1.4,
        minWidth: 185,
        cellRenderer: (p: { data: Decision }) => {
          const compPrice = p.data.competitor_price
          const dropDelta = (p.data.purchase_price || 0) - (compPrice || p.data.purchase_price || 0)
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {compPrice ? (
                <div className="grid-market-badge" data-testid="channel3-evidence">
                  <span className="c3-live-dot" title="Live Channel3 price signal" />
                  <span className="comp-domain">{p.data.competitor_name || 'Retailer'}</span>
                  <span className="comp-price">{money(compPrice)}</span>
                </div>
              ) : (
                <span style={{ fontSize: 11, color: '#94a3b8' }}>—</span>
              )}
              {dropDelta > 0 && (
                <span style={{ fontSize: 10, color: '#dc2626', fontWeight: 700 }}>
                  −{money(dropDelta)} off paid price
                </span>
              )}
            </div>
          )
        },
      },
      {
        field: 'return_probability',
        headerName: 'RETURN RISK',
        flex: 1.0,
        minWidth: 130,
        cellRenderer: (p: { value: number }) => <RiskBar probability={p.value || 0} />,
      },
      {
        headerName: 'CASE COSTINGS (AG GRID)',
        flex: 1.4,
        minWidth: 180,
        cellRenderer: (p: { data: Decision }) => {
          const returnLoss = p.data.estimated_return_cost || 0
          const diffSettle = p.data.refund_amount || 0
          const netSaved = p.data.estimated_savings || 0
          return (
            <div className="grid-cost-preview">
              <span className="cost-loss">Est. Return Loss: −{money(returnLoss)}</span>
              <span className="cost-diff">Difference Settle: {money(diffSettle)}</span>
              <span style={{ color: '#059669', fontWeight: 800 }}>Net Saved: +{money(netSaved)}</span>
            </div>
          )
        },
      },
      {
        field: 'reasoning',
        headerName: 'AI ACTUARIAL ANALYSIS',
        flex: 1.9,
        minWidth: 230,
        cellRenderer: (p: { data: Decision }) => {
          const isAi = p.data.analysis_report?.provider === 'openai' || p.data.analysis_report?.provider === 'gemini'
          return (
            <div className="grid-reasoning-cell">
              <div className="grid-reasoning-top">
                <span className={`ai-badge-sm ${isAi ? 'ai-live' : 'ai-rules'}`}>
                  <Brain size={11} /> {isAi ? 'OpenAI gpt-4.1-mini' : 'Actuarial Engine'}
                </span>
                <button
                  type="button"
                  className="inspect-link"
                  onClick={() => setInspecting(p.data)}
                  title="View detailed return cost analysis and draft resolution"
                >
                  <FileText size={11} /> Inspect Case
                </button>
              </div>
              <p className="grid-reasoning-text" title={p.data.reasoning}>
                {p.data.reasoning}
              </p>
            </div>
          )
        },
      },
      {
        field: 'status',
        headerName: 'STATUS',
        flex: 0.9,
        minWidth: 120,
        cellRenderer: (p: { value: string }) => (
          <span className={`decision-status ${p.value.toLowerCase().replace('_', '-')}`}>
            {p.value.replace('_', ' ')}
          </span>
        ),
      },
      {
        headerName: 'RESOLUTION',
        flex: 1.2,
        minWidth: 160,
        sortable: false,
        cellRenderer: (p: { data: Decision }) => {
          if (p.data.status === 'PENDING_REVIEW') {
            return (
              <button
                type="button"
                className="grid-settle-btn"
                data-testid="settle-btn"
                onClick={() => setInspecting(p.data)}
                title="Review AI recommendation, edit resolution message, and execute refund"
              >
                <Sparkles size={12} /> Review & Settle
              </button>
            )
          }
          if (p.data.status === 'APPROVED') {
            return <span className="decision-status approved">RESOLVED · REFUNDED</span>
          }
          return <span className="grid-muted">{p.data.status}</span>
        },
      },
    ],
    []
  )

  const awaiting = decisions.filter(row => row.status === 'PENDING_REVIEW')
  const resolved = decisions.filter(row => row.status !== 'PENDING_REVIEW')
  const totalSaved = resolved
    .filter(row => row.status === 'APPROVED')
    .reduce((sum, row) => sum + (row.estimated_savings || 0), 0)

  return (
    <>
      <div className="page-heading" data-testid="claims-page">
        <div>
          <div className="eyebrow">AG GRID ENTERPRISE CONSOLE · CHANNEL3 POWERED</div>
          <h1>Claims & Dispute Prevention</h1>
          <p>
            When a customer notices a price drop within their 14-day window, DropBack's Actuarial AI Agent
            compares the expensive cost of a physical box return against an instant price-difference credit via PayPal.
          </p>
        </div>
        <div className="heading-actions">
          <button type="button" className="button button-light" onClick={refresh} disabled={loading}>
            <RefreshCw size={15} /> Refresh Decisions
          </button>
        </div>
      </div>

      <div className="review-banner" data-testid="claims-banner">
        <div className="review-banner-icon"><LockKeyhole size={18} /></div>
        <div>
          <b>Human-in-the-Loop Merchant Control</b>
          <span>
            Every price protection refund requires explicit merchant approval. DropBack equips you with
            pre-calculated return costings and drafted resolution messages before you execute.
          </span>
        </div>
        <div className="review-banner-count">
          <b>{awaiting.length}</b>
          <span>claims awaiting</span>
        </div>
      </div>

      <section className="section-block grid-section">
        <div className="section-head">
          <div>
            <div className="section-title">
              Pending Claims & In-Protection Disputes <span className="count-bubble">{awaiting.length}</span>
            </div>
            <p>
              Audited by APIMatic OpenAPI context plugins and powered by real-time Channel3 competitor market signals.
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
            <div className="ag-theme-quartz grid-wrap decision-grid" data-testid="claims-grid">
              <Suspense fallback={<div className="grid-loading">Loading AG Grid table…</div>}>
                <GridTable
                  rowData={awaiting}
                  columnDefs={columns}
                  quickFilterText={quick}
                  pagination
                  paginationPageSize={10}
                />
              </Suspense>
            </div>
          </div>
        ) : (
          <div className="empty-state empty-compact">
            <div className="empty-icon"><Sparkles size={18} /></div>
            <h3>No pending claims right now</h3>
            <p>
              Customer price-match requests from the 14-Day Portal and detected Channel3 price signals will appear here for review.
            </p>
          </div>
        )}
      </section>

      {resolved.length > 0 && (
        <section className="section-block grid-section">
          <div className="section-head">
            <div>
              <div className="section-title">
                Resolved Claims History <span className="count-bubble">{resolved.length}</span>
              </div>
              <p>
                Total merchant margin protected across resolved disputes: <b>{money(totalSaved)}</b>.
              </p>
            </div>
          </div>
          <div className="table-frame">
            <div className="ag-theme-quartz grid-wrap">
              <Suspense fallback={<div className="grid-loading">Loading history table…</div>}>
                <GridTable
                  rowData={resolved}
                  columnDefs={columns}
                  pagination
                  paginationPageSize={10}
                />
              </Suspense>
            </div>
          </div>
        </section>
      )}

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

  const [settleAmount, setSettleAmount] = useState(String(refundAmt))
  const [draftedMessage, setDraftedMessage] = useState(
    decision.merchant_message ||
    decision.ai_drafted_message ||
    report?.drafted_customer_message ||
    `Hi ${decision.buyer_name || 'there'}, thank you for shopping with us! We appreciate you reaching out under our 14-day price guarantee. We've credited ${money(refundAmt, decision.currency)} directly to your PayPal account to match the competitor price, so you can keep enjoying your purchase without returning it.`
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
                CHANNEL3 LIVE COMPETITOR EVIDENCE
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
            {decision.analysis_report?.financial_breakdown && (
              <span style={{ fontSize: 11, background: '#e0f2fe', color: '#0369a1', padding: '3px 8px', borderRadius: 6, fontWeight: 700 }}>
                Indexed via Channel3 API
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
              <span className="card-hint">Credited via PayPal Orders v2 capture refund</span>
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
                <div className="fin-row"><span>Estimated Roundtrip Freight</span><b>$24.00</b></div>
                <div className="fin-row"><span>Restocking & Inspection (15%)</span><b>${((decision.purchase_price || 0) * 0.15).toFixed(2)}</b></div>
                <div className="fin-row"><span>Open-Box Markdown Loss (25%)</span><b>${((decision.purchase_price || 0) * 0.25).toFixed(2)}</b></div>
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
              <b style={{ fontSize: 12, color: '#1e293b' }}>PayPal Refund Settlement Amount:</b>
              <p style={{ margin: '2px 0 0', fontSize: 11, color: '#64748b' }}>
                Credited directly to buyer's PayPal account upon approval.
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
            <span>Human-in-the-loop: PayPal refunds are never issued automatically.</span>
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
                    <><Check size={15} /> Approve & Issue PayPal Refund</>
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
