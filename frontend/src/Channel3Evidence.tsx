import { money } from './api'

export type Channel3Market = {
  product_id?: string | null
  history?: { points: { date: string; price: number }[]; statistics?: { min_price?: number; max_price?: number; mean?: number; current_price?: number; current_status?: string } | null } | null
  retailer?: { domain: string; name: string; logo_url?: string | null } | null
  offers_checked?: number | null
  summary?: string
}

/** Channel3 evidence: who sells it, for how much, and how that compares with 90 days of prices. */
export default function Channel3Evidence({ market, offerPrice, paidPrice, currency = 'USD', compact = false }: {
  market?: Channel3Market | null; offerPrice?: number; paidPrice?: number; currency?: string; compact?: boolean
}) {
  if (!market) return null
  const points = market.history?.points || []
  const stats = market.history?.statistics
  const retailer = market.retailer
  return <div className={`c3-evidence ${compact ? 'c3-compact' : ''}`} data-testid="channel3-evidence">
    <div className="c3-head">
      <span className="c3-badge"><b>3</b> Verified by Channel3</span>
      {market.offers_checked ? <span className="c3-count">Lowest of {market.offers_checked} new, in-stock offers</span> : null}
      {retailer && <span className="c3-retailer">{retailer.logo_url && <img src={retailer.logo_url} alt="" />}<b>{retailer.name}</b><small>{retailer.domain}</small></span>}
    </div>
    {points.length > 1 && <PriceChart points={points} offerPrice={offerPrice} paidPrice={paidPrice} currency={currency} />}
    {stats && <div className="c3-stats">
      <span><small>{points.length}-day low</small><b>{money(stats.min_price || 0, currency)}</b></span>
      <span><small>Average</small><b>{money(stats.mean || 0, currency)}</b></span>
      <span><small>High</small><b>{money(stats.max_price || 0, currency)}</b></span>
      {stats.current_status && <span><small>Today's price</small><b className={`c3-status c3-${stats.current_status}`}>{stats.current_status}</b></span>}
    </div>}
    {!compact && market.summary && <p className="c3-summary">{market.summary}</p>}
  </div>
}

function PriceChart({ points, offerPrice, paidPrice, currency }: { points: { date: string; price: number }[]; offerPrice?: number; paidPrice?: number; currency: string }) {
  const W = 520, H = 96, PAD = 6
  const values = [...points.map(p => p.price), ...(paidPrice ? [paidPrice] : []), ...(offerPrice ? [offerPrice] : [])]
  const lo = Math.min(...values), hi = Math.max(...values)
  const span = hi - lo || hi * 0.1 || 1
  const x = (i: number) => PAD + (i / Math.max(1, points.length - 1)) * (W - PAD * 2)
  const y = (v: number) => PAD + (1 - (v - (lo - span * 0.15)) / (span * 1.3)) * (H - PAD * 2)
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.price).toFixed(1)}`).join(' ')
  const area = `${line} L${x(points.length - 1).toFixed(1)},${H} L${x(0).toFixed(1)},${H} Z`
  return <figure className="c3-chart">
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`Channel3 price history, ${points[0].date} to ${points[points.length - 1].date}`}>
      <path d={area} className="c3-area" />
      <path d={line} className="c3-line" vectorEffect="non-scaling-stroke" />
      {paidPrice !== undefined && <line x1={0} x2={W} y1={y(paidPrice)} y2={y(paidPrice)} className="c3-paid" vectorEffect="non-scaling-stroke" />}
      {offerPrice !== undefined && <circle cx={x(points.length - 1)} cy={y(offerPrice)} r={4} className="c3-dot" />}
    </svg>
    <figcaption>
      <span>{points[0].date}</span>
      {paidPrice !== undefined && <span className="c3-legend-paid">— paid {money(paidPrice, currency)}</span>}
      <span>{points[points.length - 1].date}</span>
    </figcaption>
  </figure>
}
