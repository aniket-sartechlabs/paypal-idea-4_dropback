import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  AlertCircle, ArrowRight, CheckCircle2,
  ExternalLink, LoaderCircle, MessageSquare, RefreshCw,
  ShieldCheck, ShoppingBag, Sparkles, TrendingDown, WalletCards,
} from 'lucide-react'
import { checkPriceForClaim, lookupOrder, money, submitClaim } from './api'
import type { Decision, PriceCheckResult } from './types'

export default function CustomerPortalPage({ toast }: { toast?: (t: { message: string; kind: 'success' | 'error' | 'info' }) => void }) {
  const { orderId } = useParams<{ orderId?: string }>()
  const location = useLocation()
  const navigate = useNavigate()

  const [lookupKey, setLookupKey] = useState(orderId || '')
  const [loading, setLoading] = useState(false)
  const [order, setOrder] = useState<any | null>(null)
  const [error, setError] = useState('')
  const [checkingPrice, setCheckingPrice] = useState(false)
  const [priceResult, setPriceResult] = useState<PriceCheckResult | null>(null)
  const [customerNotes, setCustomerNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submittedClaim, setSubmittedClaim] = useState<Decision | null>(null)

  const activeClaim: Decision | null = submittedClaim || (order?.claim as Decision) || null
  const scenarioDay = new URLSearchParams(location.search).get('scenario_day')

  const doLookup = async (key: string) => {
    if (!key.trim()) return
    setLoading(true)
    setError('')
    setPriceResult(null)
    setSubmittedClaim(null)
    try {
      const data = await lookupOrder(key.trim())
      setOrder(data)
      if (data.claim) {
        setSubmittedClaim(data.claim)
      }
    } catch (err: any) {
      setOrder(null)
      setError(err?.message || `Order '${key}' could not be found. Please check your order ID.`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (orderId) {
      setLookupKey(orderId)
      void doLookup(orderId)
    }
  }, [orderId, location.search])

  const onSubmitLookup = (e: FormEvent) => {
    e.preventDefault()
    if (lookupKey) {
      navigate(`/portal/${encodeURIComponent(lookupKey)}`)
      void doLookup(lookupKey)
    }
  }

  const handlePriceCheck = async () => {
    if (!order) return
    setCheckingPrice(true)
    setError('')
    try {
      const result = await checkPriceForClaim({
        order_id: order.id,
        product_id: order.items?.[0]?.product_id,
      })
      setPriceResult(result)
      if (result.price_drop_detected) {
        setCustomerNotes(
          `Hi Holloway team! I noticed the price for the ${result.product_name || 'item'} dropped to ${money(result.competitor_price || 0)} at ${result.competitor_name || 'authorized retailer'}. Under DropBack's 14-day price guarantee, I'd like to claim the ${money(result.drop_amount || 0)} price difference refund rather than having to repack and ship the physical box back!`
        )
      }
    } catch (err: any) {
      setError(err?.message || 'Competitor price check failed. Please try again.')
    } finally {
      setCheckingPrice(false)
    }
  }

  const handleSubmitClaim = async (e: FormEvent) => {
    e.preventDefault()
    if (!order) return
    setSubmitting(true)
    setError('')
    try {
      const claim = await submitClaim({
        order_id: order.id,
        product_id: order.items?.[0]?.product_id,
        price_drop_id: priceResult?.price_drop_id,
        customer_notes: customerNotes,
      })
      setSubmittedClaim(claim)
      toast?.({ kind: 'success', message: 'Price-match request sent to Holloway Goods for merchant review.' })
    } catch (err: any) {
      setError(err?.message || 'Could not submit claim. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const primaryItem = order?.items?.[0]
  const paidPrice = primaryItem ? Number(primaryItem.unit_price) : Number(order?.total_amount || 0)
  const merchantResolved = activeClaim?.status === 'APPROVED' || activeClaim?.status === 'REFUNDED'
  const claimSubmitted = Boolean(activeClaim)

  return (
    <div className="portal-page" data-testid="portal-page">
      <header className="portal-header">
        <div className="portal-brand">
          <span className="brand-mark"><span /><span /><span /></span>
          <span>HOLLOWAY <small style={{ fontWeight: 600, color: '#64748b' }}>ORDER & PRICE PROTECTION</small></span>
        </div>
        <nav className="buyer-account-nav"><Link to="/store">Shop</Link><span>›</span><b>Your account</b><span>›</span><b>Your orders</b></nav>
        <Link to="/store" className="portal-back-btn"><ShoppingBag size={15} /> Continue shopping</Link>
      </header>

      <div className="portal-container">
        <section className="portal-hero">
          <div>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: '#38bdf8', marginBottom: 10 }}>
              <ShieldCheck size={16} /> BUYER PRICE PROTECTION
            </div>
            <h1>Your orders & price protection</h1>
            <p>
              If the price drops within 14 days, request the difference from Holloway Goods. A merchant reviews the evidence before any PayPal refund is sent.
            </p>
            {scenarioDay && <span className="scenario-day-label">Demo timeline · Day {scenarioDay} of 14 · real Sandbox payment</span>}
          </div>
          <div className="portal-badge">
            <b>14</b>
            <span>DAYS GUARANTEE</span>
          </div>
        </section>

        <section className="order-lookup-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <b style={{ fontSize: 14, color: '#1e293b' }}>Order lookup</b>
              <p style={{ margin: '3px 0 0', fontSize: 12, color: '#64748b' }}>
                Find a PayPal purchase to check its DropBack price guarantee.
              </p>
            </div>
          </div>

          <form className="order-lookup-form" onSubmit={onSubmitLookup}>
            <input
              type="text"
              className="order-lookup-input"
              placeholder="Enter your order ID or PayPal order ID"
              value={lookupKey}
              onChange={e => setLookupKey(e.target.value)}
              required
            />
            <button type="submit" className="button button-dark" disabled={loading} style={{ minWidth: 120 }}>
              {loading ? <><LoaderCircle size={15} className="spin" /> Searching…</> : <>Find Order <ArrowRight size={15} /></>}
            </button>
          </form>

          {error && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#dc2626', fontSize: 12, background: '#fef2f2', padding: '10px 14px', borderRadius: 6 }}>
              <AlertCircle size={16} /> {error}
            </div>
          )}
        </section>

        {order && (
          <div className="journey-steps" aria-label="Price protection steps">
            <div className="journey-step complete"><span>01</span><b>Order found</b></div>
            <i />
            <div className={`journey-step ${priceResult || claimSubmitted ? 'complete' : 'current'}`}><span>02</span><b>Check price</b></div>
            <i />
            <div className={`journey-step ${claimSubmitted ? 'complete' : ''}`}><span>03</span><b>Send request</b></div>
            <i />
            <div className={`journey-step ${merchantResolved ? 'complete' : ''}`}><span>04</span><b>Merchant decision</b></div>
          </div>
        )}

        {order && (
          <section className="order-card" data-testid="buyer-order-card">
            <div className="order-card-head">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#047857', background: '#ecfdf5', padding: '2px 8px', borderRadius: 12, border: '1px solid #a7f3d0' }}>
                    <ShieldCheck size={12} style={{ display: 'inline', marginRight: 4 }} />
                    14-Day DropBack Protection Active
                  </span>
                  <span style={{ fontSize: 11, color: '#64748b' }}>
                    Ordered on {new Date(order.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                  </span>
                </div>
                <h2 style={{ margin: 0, fontSize: 18, color: '#0f172a' }}>{primaryItem?.name || 'Protected Purchase'}</h2>
                <span style={{ fontSize: 12, color: '#64748b' }}>
                    Order placed by <b>{order.buyer_name || 'Customer'}</b> · {primaryItem?.quantity || 1} item
                </span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: 11, color: '#64748b', display: 'block' }}>PURCHASE PRICE</span>
                <b style={{ fontSize: 20, color: '#0f172a' }}>{money(paidPrice, order.currency)}</b>
              </div>
            </div>

            <div className="buyer-order-product">
              {primaryItem?.image_url ? <img src={primaryItem.image_url} alt={primaryItem.name} /> : <div className="buyer-order-image-fallback"><ShoppingBag size={24} /></div>}
              <div className="buyer-order-product-copy"><span>YOUR PURCHASE</span><b>{primaryItem?.name || 'Protected purchase'}</b><small>SKU {primaryItem?.sku || '—'} · PayPal order {order.paypal_order_id || order.id.slice(0, 10)}</small></div>
              <div className="buyer-order-price"><span>ITEM PRICE</span><b>{money(paidPrice, order.currency)}</b></div>
            </div>

            {/* RESOLUTION STATUS BANNER IF CLAIM EXISTS */}
            {activeClaim && (
              <div className={`claim-status-banner ${activeClaim.status === 'PENDING_REVIEW' ? 'pending' : ''}`}>
                {activeClaim.status === 'APPROVED' || activeClaim.status === 'REFUNDED' ? (
                  <>
                    <div style={{ width: 36, height: 36, borderRadius: '50%', background: '#10b981', color: '#fff', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                      <CheckCircle2 size={22} />
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <h3>{activeClaim.settlement_mode === 'demo_ledger'
                          ? 'Merchant decision approved · demo ledger'
                          : activeClaim.refund_status === 'COMPLETED'
                            ? 'Refund credited to PayPal'
                            : 'Merchant approved your request'}</h3>
                        <span className={`portal-credit-badge ${activeClaim.settlement_mode === 'demo_ledger' ? 'demo' : ''}`}>
                          {activeClaim.settlement_mode === 'demo_ledger'
                            ? `${money(activeClaim.refund_amount, activeClaim.currency)} · DEMO`
                            : activeClaim.refund_status === 'COMPLETED'
                              ? `+${money(activeClaim.refund_amount, activeClaim.currency)} CREDITED`
                              : `REFUND ${activeClaim.refund_status || 'PROCESSING'}`}
                        </span>
                      </div>
                      <p>
                        {activeClaim.settlement_mode === 'demo_ledger'
                          ? <>This sample case was approved for <b>{money(activeClaim.refund_amount, activeClaim.currency)}</b>. It is recorded locally for the demo; no PayPal funds were moved.</>
                          : activeClaim.refund_status === 'COMPLETED'
                            ? <>Holloway credited <b>{money(activeClaim.refund_amount, activeClaim.currency)}</b> to your PayPal account. You keep your item with no return hassles.</>
                            : <>Holloway approved <b>{money(activeClaim.refund_amount, activeClaim.currency)}</b>. PayPal is still processing the refund.</>}
                      </p>
                      {(activeClaim.merchant_message || activeClaim.ai_drafted_message) && (
                        <div style={{ marginTop: 12, background: '#fff', border: '1px solid #d1fae5', borderRadius: 8, padding: 12 }}>
                          <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '0.05em', color: '#047857', display: 'flex', alignItems: 'center', gap: 5 }}>
                            <MessageSquare size={12} /> PERSONAL MESSAGE FROM HOLLOWAY GOODS
                          </span>
                          <p style={{ margin: '6px 0 0', fontSize: 12, color: '#1e293b', fontStyle: 'italic', lineHeight: 1.5 }}>
                            "{activeClaim.merchant_message || activeClaim.ai_drafted_message}"
                          </p>
                        </div>
                      )}
                      <div style={{ marginTop: 10, fontSize: 11, color: '#047857', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <WalletCards size={13} />
                        <span>{activeClaim.settlement_mode === 'demo_ledger'
                          ? 'Sample order · local demo ledger'
                          : `PayPal Sandbox · ${activeClaim.paypal_refund_id || 'refund reference pending'}`}</span>
                      </div>
                    </div>
                  </>
                ) : activeClaim.status === 'PENDING_REVIEW' ? (
                  <>
                    <div style={{ width: 36, height: 36, borderRadius: '50%', background: '#3b82f6', color: '#fff', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                      <Sparkles size={20} />
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <h3>Price-Match Claim Under Merchant Review</h3>
                        <span style={{ background: '#2563eb', color: '#fff', fontSize: 11, fontWeight: 800, padding: '3px 10px', borderRadius: 20 }}>
                          PENDING SETTLEMENT
                        </span>
                      </div>
                      <p>
                        Our Actuarial AI Agent evaluated your claim against Channel3's competitor price.
                        The recommended difference settlement of <b>{money(activeClaim.refund_amount, activeClaim.currency)}</b> is currently in the merchant's review queue.
                      </p>
                      {activeClaim.customer_notes && (
                        <div style={{ marginTop: 10, background: '#fff', border: '1px solid #dbeafe', borderRadius: 8, padding: 10 }}>
                          <span style={{ fontSize: 10, fontWeight: 700, color: '#1e40af' }}>Your claim note:</span>
                          <p style={{ margin: '4px 0 0', fontSize: 11, color: '#334155' }}>"{activeClaim.customer_notes}"</p>
                        </div>
                      )}
                    </div>
                  </>
                ) : (
                  <div style={{ flex: 1 }}>
                    <h3>Claim Status: {activeClaim.status}</h3>
                    <p>{activeClaim.merchant_message || 'Your claim has been processed.'}</p>
                  </div>
                )}
              </div>
            )}

            {/* LIVE PRICE GUARANTEE CHECKER IF NO ACTIVE CLAIM OR TO RE-CHECK */}
            {!activeClaim && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className={`price-check-box ${priceResult?.price_drop_detected ? 'price-check-detected' : ''}`}>
                <div className="price-check-info">
                  <b>Check the live market price</b>
                  <span>
                    {priceResult
                      ? priceResult.price_drop_detected
                        ? `${priceResult.evidence_source === 'demo_offer_fixture' ? 'Demo offer found' : 'Channel3 found a lower offer'} at ${priceResult.competitor_name}.`
                        : `No lower offer found. Your purchase price is ${money(paidPrice, order.currency)}.`
                      : 'DropBack checks current offers for the exact product you bought.'}
                    </span>
                  </div>
                  <div>
                    <button
                      type="button"
                      data-testid="price-check-btn"
                      className="button button-accent"
                      onClick={handlePriceCheck}
                      disabled={checkingPrice}
                    >
                      {checkingPrice ? <><LoaderCircle size={15} className="spin" /> Checking Channel3…</> : <><RefreshCw size={15} /> Check Live Market Price</>}
                    </button>
                  </div>
                </div>

                {priceResult?.price_drop_detected && (
                  <div className="claim-submission-card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <TrendingDown size={18} color="#dc2626" />
                        <div>
                          <b style={{ fontSize: 13, color: '#1e293b' }}>
                            {priceResult.evidence_source === 'demo_offer_fixture' ? 'Demo offer' : 'Lower price'} at {priceResult.competitor_name}: {money(priceResult.competitor_price || 0, order.currency)}
                          </b>
                          <div style={{ fontSize: 11, color: '#64748b' }}>
                            Original Holloway Price: <s>{money(paidPrice, order.currency)}</s> · Difference: <span style={{ color: '#dc2626', fontWeight: 700 }}>−{money(priceResult.drop_amount || 0, order.currency)} ({priceResult.drop_percentage}%)</span>
                          </div>
                        </div>
                      </div>
                      <span className="price-drop-delta-badge">−{money(priceResult.drop_amount || 0)} OFF</span>
                    </div>

                    {priceResult.best_offer?.url && (
                      <div style={{ fontSize: 11, color: '#3b82f6' }}>
                        <a href={priceResult.best_offer.url} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        View offer at {priceResult.competitor_name} <ExternalLink size={12} />
                        </a>
                      </div>
                    )}

                    <form onSubmit={handleSubmitClaim} style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 8 }}>
                      <label style={{ fontSize: 11, fontWeight: 700, color: '#334155' }}>
                        Add a note for Holloway Goods (Price Match / Return Prevention Request):
                        <textarea
                          value={customerNotes}
                          onChange={e => setCustomerNotes(e.target.value)}
                          placeholder="Tell the merchant why you are requesting a price match..."
                          required
                        />
                      </label>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 11, color: '#64748b' }}>
                          ⚡ Instant settlement prevents physical return shipping and repackaging.
                        </span>
                        <button type="submit" data-testid="submit-claim-btn" className="button button-dark" disabled={submitting || priceResult.protection_active === false}>
                          {submitting ? <><LoaderCircle size={15} className="spin" /> Submitting…</> : <>Submit Price-Match Claim <ArrowRight size={15} /></>}
                        </button>
                      </div>
                    </form>
                  </div>
                )}
              </div>
            )}

            {activeClaim?.status === 'PENDING_REVIEW' && (
              <div className="buyer-next-step">
                <div><b>Your request is with Holloway Goods</b><span>The merchant sees your note, market evidence, and return-cost estimate in the claims workspace.</span></div>
                <Link to="/login?demo=merchant&next=%2Fclaims" className="button button-dark">Continue to merchant review <ArrowRight size={15} /></Link>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
