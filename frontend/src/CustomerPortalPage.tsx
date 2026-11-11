import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  AlertCircle, ArrowLeft, ArrowRight, CheckCircle2,
  ExternalLink, LoaderCircle, MessageSquare, RefreshCw,
  ShieldCheck, Sparkles, TrendingDown, WalletCards,
} from 'lucide-react'
import { checkPriceForClaim, lookupOrder, money, submitClaim } from './api'
import type { Decision, PriceCheckResult } from './types'

export default function CustomerPortalPage({ toast }: { toast?: (t: { message: string; kind: 'success' | 'error' | 'info' }) => void }) {
  const { orderId } = useParams<{ orderId?: string }>()
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
  }, [orderId])

  const onSubmitLookup = (e: FormEvent) => {
    e.preventDefault()
    if (lookupKey) {
      navigate(`/portal/${encodeURIComponent(lookupKey)}`)
      void doLookup(lookupKey)
    }
  }

  const quickLookup = (id: string) => {
    setLookupKey(id)
    navigate(`/portal/${encodeURIComponent(id)}`)
    void doLookup(id)
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
        customer_notes: customerNotes,
      })
      setSubmittedClaim(claim)
      toast?.({ kind: 'success', message: 'Price-match claim submitted! Holloway AI agent has prepared the case for merchant review.' })
    } catch (err: any) {
      setError(err?.message || 'Could not submit claim. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const primaryItem = order?.items?.[0]
  const paidPrice = primaryItem ? Number(primaryItem.unit_price) : Number(order?.total_amount || 0)

  return (
    <div className="portal-page" data-testid="portal-page">
      <header className="portal-header">
        <div className="portal-brand">
          <span className="brand-mark"><span /><span /><span /></span>
          <span>DROPBACK <small style={{ fontWeight: 600, color: '#64748b' }}>14-DAY PRICE COVER</small></span>
        </div>
        <Link to="/store" className="portal-back-btn">
          <ArrowLeft size={15} /> Back to Holloway Storefront
        </Link>
      </header>

      <div className="portal-container">
        <section className="portal-hero">
          <div>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: '#38bdf8', marginBottom: 10 }}>
              <ShieldCheck size={16} /> AUTOMATED PRICE MATCH & RETURN PREVENTION
            </div>
            <h1>Customer Price Protection Portal</h1>
            <p>
              Bought an item from Holloway Goods? If an authorized competitor drops the price within 14 days,
              we refund you the difference directly to your PayPal account so you never have to return the physical box.
            </p>
          </div>
          <div className="portal-badge">
            <b>14</b>
            <span>DAYS GUARANTEE</span>
          </div>
        </section>

        <section className="order-lookup-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <b style={{ fontSize: 14, color: '#1e293b' }}>Look Up Your Order</b>
              <p style={{ margin: '3px 0 0', fontSize: 12, color: '#64748b' }}>
                Enter your order ID or PayPal transaction ID to check live market price matching.
              </p>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: '#94a3b8' }}>Demo quick-fill:</span>
              <button
                type="button"
                className="button button-light small-button"
                style={{ fontSize: 11, padding: '4px 8px' }}
                onClick={() => quickLookup('sample-order-maya-sony')}
              >
                Maya Chen (Sony WH-1000XM5)
              </button>
              <button
                type="button"
                className="button button-light small-button"
                style={{ fontSize: 11, padding: '4px 8px' }}
                onClick={() => quickLookup('sample-order-rohan-breville')}
              >
                Rohan Shah (Barista Express)
              </button>
            </div>
          </div>

          <form className="order-lookup-form" onSubmit={onSubmitLookup}>
            <input
              type="text"
              className="order-lookup-input"
              placeholder="e.g. sample-order-maya-sony or your PayPal Order ID"
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
          <section className="order-card">
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
                  SKU: <b>{primaryItem?.sku || '—'}</b> · Buyer: <b>{order.buyer_name || 'Customer'}</b> ({order.buyer_email || '—'})
                </span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: 11, color: '#64748b', display: 'block' }}>PURCHASE PRICE</span>
                <b style={{ fontSize: 20, color: '#0f172a' }}>{money(paidPrice, order.currency)}</b>
              </div>
            </div>

            {/* RESOLUTION STATUS BANNER IF CLAIM EXISTS */}
            {activeClaim && (
              <div className={`claim-status-banner ${activeClaim.status === 'PENDING_REVIEW' ? 'pending' : ''}`}>
                {activeClaim.status === 'APPROVED' ? (
                  <>
                    <div style={{ width: 36, height: 36, borderRadius: '50%', background: '#10b981', color: '#fff', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                      <CheckCircle2 size={22} />
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <h3>Claim Approved! Refund Credited to PayPal</h3>
                        <span style={{ background: '#059669', color: '#fff', fontSize: 11, fontWeight: 800, padding: '3px 10px', borderRadius: 20 }}>
                          +{money(activeClaim.refund_amount, activeClaim.currency)} CREDITED
                        </span>
                      </div>
                      <p>
                        Your price-match claim has been approved by Holloway Goods. The price difference of{' '}
                        <b>{money(activeClaim.refund_amount, activeClaim.currency)}</b> was credited directly back to your PayPal balance.
                        You keep your item with no return hassles!
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
                        <span>Refund processed via PayPal Sandbox Orders v2 / Captures Refund.</span>
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
                    <b>Live Channel3 Competitor Price Check</b>
                    <span>
                      {priceResult
                        ? priceResult.price_drop_detected
                          ? `Competitor price drop confirmed at ${priceResult.competitor_name}!`
                          : `Channel3 verified: You currently have the best available market price (${money(paidPrice)}).`
                        : 'Channel3 scans online retailers (B&H Photo, Macy’s, Best Buy, Abt) for lower active offers.'}
                    </span>
                  </div>
                  <div>
                    <button
                      type="button"
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
                            Lower Price Verified at {priceResult.competitor_name}: {money(priceResult.competitor_price || 0)}
                          </b>
                          <div style={{ fontSize: 11, color: '#64748b' }}>
                            Original Holloway Price: <s>{money(paidPrice)}</s> · Drop: <span style={{ color: '#dc2626', fontWeight: 700 }}>−{money(priceResult.drop_amount || 0)} ({priceResult.drop_percentage}%)</span>
                          </div>
                        </div>
                      </div>
                      <span className="price-drop-delta-badge">−{money(priceResult.drop_amount || 0)} OFF</span>
                    </div>

                    {priceResult.best_offer?.url && (
                      <div style={{ fontSize: 11, color: '#3b82f6' }}>
                        <a href={priceResult.best_offer.url} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          Inspect competitor offer on {priceResult.competitor_name} <ExternalLink size={12} />
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
                        <button type="submit" className="button button-dark" disabled={submitting}>
                          {submitting ? <><LoaderCircle size={15} className="spin" /> Submitting…</> : <>Submit Price-Match Claim <ArrowRight size={15} /></>}
                        </button>
                      </div>
                    </form>
                  </div>
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
