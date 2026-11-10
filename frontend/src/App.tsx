import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { ColDef } from 'ag-grid-community'
import { Link, NavLink, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity, ArrowDownRight, ArrowRight, Check, CheckCircle2,
  CircleHelp, ExternalLink, Eye, LayoutDashboard, LoaderCircle, LockKeyhole,
  LogOut, Package, Plus, RefreshCw, RotateCcw, Search, Settings2, ShieldCheck, ShoppingBag, Sparkles,
  Store, TrendingDown, WalletCards, X,
} from 'lucide-react'
import { api, getDecisions, getDrops, getOrders, getProducts, getSettings, getStats, money } from './api'
import type { Decision, Order, PriceDrop, Product, Stats } from './types'

declare global {
  interface Window {
    paypal?: {
      createInstance: (options: { clientId: string; components?: string[]; pageType?: string }) => Promise<{
        findEligibleMethods: (options: { currencyCode: string }) => Promise<{ isEligible: (method: string) => boolean }>
        createPayPalOneTimePaymentSession: (options: {
          onApprove: (data: { orderId: string }) => Promise<void> | void
          onCancel?: () => void
          onError?: (error: Error) => void
        }) => { start: (options: { presentationMode: 'auto' }, order: Promise<{ orderId: string }>) => Promise<void> }
      }>
    }
  }
}

const GridTable = lazy(() => import('./GridTable'))

type Toast = { message: string; kind: 'success' | 'error' | 'info' }

function App() {
  const [auth, setAuth] = useState<{ loading: boolean; authenticated: boolean; email?: string }>({ loading: true, authenticated: false })
  const [toast, setToast] = useState<Toast | null>(null)
  const location = useLocation()
  const navigate = useNavigate()

  const refreshAuth = useCallback(async () => {
    try {
      const value = await api<{ authenticated: boolean; email?: string }>('/auth/me')
      setAuth({ loading: false, ...value })
    } catch {
      setAuth({ loading: false, authenticated: false })
    }
  }, [])

  useEffect(() => { void refreshAuth() }, [refreshAuth])
  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(null), 4200)
    return () => window.clearTimeout(timeout)
  }, [toast])

  const onLogin = (email: string) => {
    setAuth({ loading: false, authenticated: true, email })
    setToast({ message: 'Welcome back. Your merchant workspace is ready.', kind: 'success' })
    navigate('/', { replace: true })
  }
  const onLogout = async () => {
    await api('/auth/logout', { method: 'POST' }).catch(() => undefined)
    setAuth({ loading: false, authenticated: false })
    navigate('/login', { replace: true })
  }

  if (auth.loading && location.pathname !== '/store') return <div className="loading-screen"><LoaderCircle className="spin" size={22} /><span>Opening your workspace</span></div>

  return <>
    <Routes>
      <Route path="/store" element={<Storefront publicMode toast={setToast} />} />
      <Route path="/login" element={auth.authenticated ? <Navigate to="/" replace /> : <Login onLogin={onLogin} />} />
      <Route element={auth.authenticated ? <Shell email={auth.email || ''} onLogout={onLogout} /> : <Login onLogin={onLogin} />}>
        <Route path="/" element={<DashboardPage toast={setToast} />} />
        <Route path="/products" element={<ProductsPage toast={setToast} />} />
        <Route path="/price-drops" element={<PriceDropsPage toast={setToast} />} />
        <Route path="/agent" element={<DecisionsPage toast={setToast} />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/settings" element={<SettingsPage toast={setToast} />} />
        <Route path="/checkout/return" element={<CheckoutStatus success />} />
        <Route path="/checkout/cancel" element={<CheckoutStatus success={false} />} />
      </Route>
      <Route path="*" element={<div className="not-found"><h2>That page isn't here</h2><Link to="/">Go to overview</Link></div>} />
    </Routes>
    {toast && <div className={`toast toast-${toast.kind}`} role="status"><span className="toast-icon">{toast.kind === 'success' ? <CheckCircle2 size={18} /> : toast.kind === 'error' ? <X size={18} /> : <Activity size={18} />}</span>{toast.message}</div>}
  </>
}

function Login({ onLogin }: { onLogin: (email: string) => void }) {
  const [email, setEmail] = useState(import.meta.env.DEV ? 'demo@dropback.local' : '')
  const [password, setPassword] = useState(import.meta.env.DEV ? 'dropback-demo' : '')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [show, setShow] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setPending(true)
    setError('')
    try {
      const result = await api<{ email: string }>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
      onLogin(result.email)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign in. Please try again.')
    } finally { setPending(false) }
  }

  return <div className="login-page">
    <div className="login-art">
      <div className="login-art-top"><BrandMark /> <span>DROPBACK</span></div>
      <div className="login-quote">
        <div className="quote-tag"><span className="pulse-dot" /> PRICE PROTECTION, AUTOMATED</div>
        <h1>Keep the customer.<br /><em>Give back the difference.</em></h1>
        <p>When a price falls, DropBack helps you refund the difference before a buyer has to ask.</p>
        <div className="login-proof"><div className="avatar-stack"><i>MC</i><i>RS</i><i>JL</i><i>+4</i></div><span>Thoughtful refunds. Better retention.</span></div>
      </div>
      <div className="login-art-bottom"><span>DROPBACK FOR MERCHANTS</span><span>BUILT AROUND THE BUYER</span></div>
    </div>
    <div className="login-panel">
      <div className="login-mobile-brand"><BrandMark /><span>DROPBACK</span></div>
      <div className="login-form-wrap">
        <div className="login-eyebrow">MERCHANT CONSOLE</div>
        <h2>Welcome back</h2>
        <p className="muted">Sign in to see where your next customer save is hiding.</p>
        <form className="login-form" onSubmit={submit}>
          <label>Email address<div className="input-wrap"><span className="field-icon">@</span><input autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} required type="email" /></div></label>
          <label>Password<div className="input-wrap"><LockKeyhole size={16} className="field-icon" /><input autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required type={show ? 'text' : 'password'} /><button className="reveal-button" type="button" onClick={() => setShow(value => !value)} aria-label={show ? 'Hide password' : 'Show password'}><Eye size={16} /></button></div></label>
          {error && <div className="form-error">{error}</div>}
          <button className="button button-dark login-submit" disabled={pending} type="submit">{pending ? <><LoaderCircle size={16} className="spin" /> Signing in…</> : <>Sign in <ArrowRight size={17} /></>}</button>
        </form>
        {import.meta.env.DEV && <div className="demo-login"><Sparkles size={15} /><div><strong>First time here?</strong><span>Demo access is ready for you.</span><code>demo@dropback.local <b>·</b> dropback-demo</code></div></div>}
        <div className="login-safe"><ShieldCheck size={15} /> Your merchant workspace is private and protected.</div>
      </div>
      <div className="login-footer"><span>© 2026 DropBack</span><a href="mailto:support@dropback.example">Need help?</a></div>
    </div>
  </div>
}

function BrandMark() { return <span className="brand-mark"><span /><span /><span /></span> }

const nav = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/products', label: 'Products', icon: Package },
  { to: '/price-drops', label: 'Price drops', icon: TrendingDown, badge: true },
  { to: '/agent', label: 'Agent review', icon: Sparkles },
  { to: '/orders', label: 'Orders', icon: ShoppingBag },
]

function Shell({ email, onLogout }: { email: string; onLogout: () => void }) {
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [pendingDrops, setPendingDrops] = useState(0)
  useEffect(() => { getDrops().then(rows => setPendingDrops(rows.filter(row => !row.processed).length)).catch(() => undefined) }, [location.pathname])
  const title = nav.find(item => (item.end && location.pathname === '/') || item.to === location.pathname)?.label || 'Settings'
  return <div className="app-shell">
    <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}>
      <Link to="/" className="brand-lockup"><BrandMark /><span>DROPBACK<small>MERCHANT CONSOLE</small></span></Link>
      <div className="side-caption">WORKSPACE</div>
      <nav className="side-nav">{nav.map(item => <NavLink key={item.to} to={item.to} end={item.end} onClick={() => setOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><item.icon size={18} strokeWidth={1.8} /><span>{item.label}</span>{item.badge && pendingDrops > 0 && <i className="nav-badge">{pendingDrops}</i>}</NavLink>)}</nav>
      <div className="side-caption side-caption-lower">MANAGE</div>
      <NavLink to="/settings" onClick={() => setOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><Settings2 size={18} strokeWidth={1.8} /><span>Settings</span></NavLink>
      <div className="sidebar-spacer" />
      <Link to="/store" target="_blank" className="store-shortcut"><span className="shortcut-icon"><Store size={16} /></span><span><b>Open storefront</b><small>See the buyer experience</small></span><ExternalLink size={14} /></Link>
      <div className="sidebar-user"><div className="user-avatar">{email.slice(0, 1).toUpperCase()}</div><div className="user-info"><b>{email.split('@')[0]}</b><span>Store owner</span></div><button className="icon-button logout-button" onClick={onLogout} title="Sign out" aria-label="Sign out"><LogOut size={17} /></button></div>
    </aside>
    <main className="main-shell">
      <header className="topbar"><button className="mobile-menu" onClick={() => setOpen(value => !value)} aria-label="Toggle menu">☰</button><div className="breadcrumb"><span>Workspace</span><span className="breadcrumb-slash">/</span><b>{title}</b></div><div className="topbar-actions"><div className="sandbox-pill"><span /> SANDBOX</div><button className="icon-button help-button" title="Help"><CircleHelp size={18} /></button><div className="topbar-avatar">{email.slice(0, 1).toUpperCase()}</div></div></header>
      <div className="page-wrap"><Outlet /></div>
    </main>
  </div>
}

function PageHeading({ eyebrow, title, description, right }: { eyebrow: string; title: string; description: string; right?: ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{right && <div className="heading-actions">{right}</div>}</div>
}

function useWorkspaceData() {
  const [products, setProducts] = useState<Product[]>([])
  const [drops, setDrops] = useState<PriceDrop[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [p, d, a, o, s] = await Promise.all([getProducts(), getDrops(), getDecisions(), getOrders(), getStats()])
      setProducts(p); setDrops(d); setDecisions(a); setOrders(o); setStats(s)
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])
  return { products, drops, decisions, orders, stats, loading, refresh, setProducts, setDrops, setDecisions }
}

function DashboardPage({ toast }: { toast: (value: Toast) => void }) {
  const { products, drops, decisions, orders, stats, loading, refresh } = useWorkspaceData()
  const [checking, setChecking] = useState(false)
  const pending = decisions.filter(row => row.decision === 'REFUND' && row.status === 'PENDING_REVIEW')
  const unprocessed = drops.filter(row => !row.processed)

  async function checkPrices() {
    setChecking(true)
    let created = 0
    try {
      for (const product of products) {
        const result = await api<{ price_drop?: PriceDrop | null; matched?: boolean }>(`/products/${product.id}/channel3-check`, { method: 'POST' })
        if (result.price_drop) created++
      }
      await refresh()
      toast({ kind: 'success', message: created ? `${created} new Channel3 price drop${created > 1 ? 's' : ''} detected.` : 'Channel3 checked all products. No new price drops.' })
    } catch (error) {
      toast({ kind: 'error', message: error instanceof Error ? error.message : 'Channel3 check could not finish.' })
    } finally { setChecking(false) }
  }

  return <>
    <PageHeading eyebrow="MONDAY, NOVEMBER 10, 2026" title="Good morning, merchant." description="Protect the customer relationship while keeping an eye on every dollar." right={<><Link className="button button-light" to="/store"><Store size={16} /> View storefront</Link><button className="button button-accent" onClick={checkPrices} disabled={checking}>{checking ? <LoaderCircle size={16} className="spin" /> : <RefreshCw size={16} />}{checking ? 'Checking offers…' : 'Check Channel3 prices'}</button></>} />
    <div className="welcome-strip"><div className="welcome-icon"><Sparkles size={19} /></div><div><b>Your price protection is looking good.</b><span>Channel3 keeps your catalog connected to live offers. Review recommendations before any refund is sent.</span></div><Link to="/settings" aria-label="Open settings"><ArrowRight size={18} /></Link></div>
    {!stats?.channel3_configured && <div className="connection-callout"><span className="connection-light" /><div><b>Connect Channel3 to start live price monitoring</b><span>Add <code>CHANNEL3_API_KEY</code> to the backend <code>.env</code>, then restart the API. The “Check prices” action queries live offers and starts product subscriptions.</span></div><Link to="/settings">View setup <ArrowRight size={15} /></Link></div>}
    <div className="metrics-grid">
      <Metric label="Orders protected" value={String(stats?.orders_exposed ?? '—')} note="Within protection window" icon={<ShieldCheck size={18} />} tint="green" trend={`${stats?.orders_total ?? 0} orders total`} />
      <Metric label="Awaiting review" value={String(stats?.recommendations_pending ?? '—')} note="Refund recommendations" icon={<Sparkles size={18} />} tint="purple" trend={`${pending.length} ready`} />
      <Metric label="Refunded to buyers" value={money(stats?.total_refunded || 0)} note={`${stats?.refunds_issued ?? 0} completed refunds`} icon={<WalletCards size={18} />} tint="blue" trend="All time" />
      <Metric label="Estimated savings" value={money(stats?.estimated_savings || 0)} note="Versus a full return" icon={<TrendingDown size={18} />} tint="orange" trend={`${stats?.estimated_returns_avoided ?? 0} returns avoided`} />
    </div>
    <section className="section-block">
      <div className="section-head"><div><div className="section-title">Needs your attention <span className="count-bubble">{pending.length + unprocessed.length}</span></div><p>Live price changes and agent recommendations, all in one place.</p></div><Link to="/price-drops" className="text-link">See all activity <ArrowRight size={15} /></Link></div>
      <div className="attention-grid">
        <div className="attention-card"><div className="attention-top"><div className="attention-symbol symbol-mint"><TrendingDown size={17} /></div><span className="status-tag status-waiting">PRICE CHANGE</span></div><h3>{unprocessed.length ? `${unprocessed.length} price change${unprocessed.length > 1 ? 's' : ''} need processing` : 'Keep an eye on the catalog'}</h3><p>{unprocessed.length ? 'Match eligible buyers and calculate savings before reviewing refund actions.' : 'Run a Channel3 check to look for a lower live offer across retailers.'}</p><Link to="/price-drops" className="card-link">Review price changes <ArrowRight size={15} /></Link></div>
        <div className="attention-card"><div className="attention-top"><div className="attention-symbol symbol-lilac"><Sparkles size={17} /></div><span className="status-tag status-review">AGENT REVIEW</span></div><h3>{pending.length ? `${pending.length} refund recommendation${pending.length > 1 ? 's' : ''} ready` : 'No decisions waiting'}</h3><p>{pending.length ? 'See the return risk, refund amount, and estimated savings for each buyer.' : 'When a price drop is processed, eligible recommendations appear here for approval.'}</p><Link to="/agent" className="card-link">Open agent review <ArrowRight size={15} /></Link></div>
      </div>
    </section>
    <section className="section-block overview-lower">
      <div className="section-head"><div><div className="section-title">Recent orders</div><p>Most recent buyers in the protection window.</p></div><Link to="/orders" className="text-link">All orders <ArrowRight size={15} /></Link></div>
      <div className="table-frame"><div className="ag-theme-quartz grid-wrap grid-compact"><Suspense fallback={<div className="grid-loading">Preparing order table…</div>}><GridTable rowData={orders.slice(0, 5)} columnDefs={orderColumns} domLayout="autoHeight" /></Suspense></div></div>
    </section>
    {loading && <div className="refresh-indicator"><LoaderCircle className="spin" size={14} /> Updating workspace</div>}
  </>
}

function Metric({ label, value, note, icon, tint, trend }: { label: string; value: string; note: string; icon: ReactNode; tint: string; trend: string }) {
  return <div className="metric-card"><div className={`metric-icon ${tint}`}>{icon}</div><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-bottom"><span>{note}</span><span className="metric-trend">{trend}</span></div></div>
}

const orderColumns: ColDef<Order>[] = [
  { field: 'paypal_order_id', headerName: 'ORDER', flex: 1.1, minWidth: 125, valueFormatter: p => p.value ? `#${String(p.value).slice(-8).toUpperCase()}` : `#${p.data?.id.slice(0, 8).toUpperCase()}` },
  { field: 'buyer_name', headerName: 'BUYER', flex: 1.2, minWidth: 135, valueFormatter: p => p.value || 'Sample buyer' },
  { headerName: 'ITEM', flex: 1.5, minWidth: 170, valueGetter: p => p.data?.items.map(item => item.name).join(', ') || '—' },
  { field: 'total_amount', headerName: 'TOTAL', flex: 0.7, minWidth: 95, valueFormatter: p => money(p.value, p.data?.currency) },
  { field: 'status', headerName: 'STATUS', flex: 0.8, minWidth: 100, cellRenderer: (p: { value: string }) => <span className={`order-status ${p.value === 'COMPLETED' ? 'complete' : 'pending'}`}><i />{p.value === 'COMPLETED' ? 'Captured' : p.value}</span> },
  { field: 'created_at', headerName: 'PLACED', flex: 0.9, minWidth: 110, valueFormatter: p => p.value ? new Date(p.value).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—' },
]

function ProductsPage({ toast }: { toast: (value: Toast) => void }) {
  const { products, refresh } = useWorkspaceData()
  const [checkingId, setCheckingId] = useState('')
  const [newPrice, setNewPrice] = useState<Record<string, string>>({})
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ name: '', sku: '', category: 'Electronics', current_price: '', description: '' })

  async function liveCheck(product: Product) {
    setCheckingId(product.id)
    try {
      const result = await api<{ matched: boolean; title?: string; best_offer?: { price: number; merchant: string }; price_drop?: PriceDrop | null; subscription_active?: boolean; message?: string }>(`/products/${product.id}/channel3-check`, { method: 'POST' })
      if (!result.matched) toast({ kind: 'info', message: result.message || 'Channel3 could not confidently match this product.' })
      else toast({ kind: 'success', message: result.price_drop ? `Price change found at ${result.best_offer?.merchant}. Process it to evaluate buyers.` : `Checked ${result.title}: ${money(result.best_offer?.price || 0)} at ${result.best_offer?.merchant}.` })
      await refresh()
    } catch (error) { toast({ kind: 'error', message: error instanceof Error ? error.message : 'Channel3 check failed.' }) }
    finally { setCheckingId('') }
  }

  async function changeMerchantPrice(event: FormEvent, product: Product) {
    event.preventDefault()
    const value = newPrice[product.id]
    if (!value) return
    try {
      const result = await api<{ price_drop?: PriceDrop | null }>(`/products/${product.id}/price`, { method: 'PATCH', body: JSON.stringify({ new_price: Number(value) }) })
      toast({ kind: 'success', message: result.price_drop ? 'Merchant price update recorded as a price drop.' : 'Merchant price updated.' })
      await refresh()
    } catch (error) { toast({ kind: 'error', message: error instanceof Error ? error.message : 'Price update failed.' }) }
  }

  async function addProduct(event: FormEvent) {
    event.preventDefault()
    try {
      await api('/products', { method: 'POST', body: JSON.stringify({ ...form, current_price: Number(form.current_price) }) })
      setForm({ name: '', sku: '', category: 'Electronics', current_price: '', description: '' })
      setAdding(false); await refresh(); toast({ kind: 'success', message: 'Product added to your catalog.' })
    } catch (error) { toast({ kind: 'error', message: error instanceof Error ? error.message : 'Product could not be added.' }) }
  }

  return <>
    <PageHeading eyebrow="CATALOG & PRICE MONITORING" title="Products" description="Connect each product to Channel3 and keep prices current across the market." right={<button className="button button-dark" onClick={() => setAdding(true)}><Plus size={16} /> Add product</button>} />
    <div className="product-info"><div className="product-info-icon"><Activity size={18} /></div><div><b>Channel3 is your live price signal</b><span>Channel3 price monitoring is required. Use the exact product title or matching SKU to avoid linking a different model.</span></div><span className="source-chip"><span /> CHANNEL3 API</span></div>
    {adding && <form className="add-product-form" onSubmit={addProduct}><div className="form-heading"><div><b>Add a product</b><span>Use the exact Channel3 product title or matching SKU so price alerts stay on the right item.</span></div><button type="button" className="icon-button" onClick={() => setAdding(false)} aria-label="Close"><X size={18} /></button></div><div className="form-grid"><label>Product name<input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label><label>SKU<input required value={form.sku} onChange={e => setForm({ ...form, sku: e.target.value })} /></label><label>Category<input value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} /></label><label>Current price<input required type="number" min="0.01" step="0.01" value={form.current_price} onChange={e => setForm({ ...form, current_price: e.target.value })} /></label></div><label className="full-field">Short description<input value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></label><button className="button button-dark" type="submit">Add to catalog <ArrowRight size={16} /></button></form>}
    <div className="product-list">{products.map((product, i) => <article className="product-row" key={product.id}>
      <div className={`product-art art-${i % 3}`}><span>{product.category === 'Appliances' ? '☕' : product.category === 'Electronics' ? '◉' : '▱'}</span></div>
      <div className="product-copy"><div className="product-name-line"><h3>{product.name}</h3><span className={`connection-status ${product.channel3_connected ? 'connected' : ''}`}><i />{product.channel3_connected ? 'Channel3 linked' : 'Not checked yet'}</span></div><div className="product-meta"><span>SKU <b>{product.sku}</b></span><span>{product.category}</span><span>{product.protection_days}-day protection</span></div></div>
      <div className="product-price-box"><span>MERCHANT PRICE</span><b>{money(product.current_price, product.currency)}</b></div>
      <div className="product-controls"><button className="button button-light small-button" onClick={() => liveCheck(product)} disabled={checkingId === product.id}>{checkingId === product.id ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />} Check live price</button><form className="price-edit" onSubmit={event => changeMerchantPrice(event, product)}><input aria-label={`New merchant price for ${product.name}`} type="number" min="0.01" step="0.01" placeholder="New price" value={newPrice[product.id] || ''} onChange={e => setNewPrice({ ...newPrice, [product.id]: e.target.value })} /><button disabled={!newPrice[product.id]} className="icon-button" title="Record merchant price update"><ArrowDownRight size={17} /></button></form></div>
    </article>)}</div>
  </>
}

function PriceDropsPage({ toast }: { toast: (value: Toast) => void }) {
  const { drops, refresh } = useWorkspaceData()
  const [running, setRunning] = useState('')
  async function process(drop: PriceDrop) {
    setRunning(drop.id)
    try {
      const result = await api<Decision[]>(`/price-drops/${drop.id}/process`, { method: 'POST' })
      const recommendations = result.filter(row => row.decision === 'REFUND').length
      toast({ kind: 'success', message: `${result.length} order${result.length === 1 ? '' : 's'} evaluated; ${recommendations} refund recommendation${recommendations === 1 ? '' : 's'} created.` })
      await refresh()
    } catch (error) { toast({ kind: 'error', message: error instanceof Error ? error.message : 'The price drop could not be processed.' }) }
    finally { setRunning('') }
  }
  return <>
    <PageHeading eyebrow="PRICE SIGNALS" title="Price drops" description="Market changes from Channel3 and merchant price updates, with eligible buyers ready to evaluate." right={<Link to="/products" className="button button-light"><RefreshCw size={16} /> Check product prices</Link>} />
    {drops.length === 0 ? <EmptyState icon={<TrendingDown size={20} />} title="No price drops yet" copy="Check your products with Channel3 to get a live offer signal. Any detected changes will show up here." action={<Link className="button button-dark" to="/products">Connect product prices <ArrowRight size={16} /></Link>} /> : <div className="drop-list">{drops.map(drop => <article className="drop-card" key={drop.id}><div className="drop-icon"><TrendingDown size={19} /></div><div className="drop-main"><div className="drop-title-row"><h3>{drop.product_name}</h3><span className={`source-label ${drop.source === 'channel3' ? 'channel' : 'manual'}`}>{drop.source === 'channel3' ? 'CHANNEL3' : 'MERCHANT UPDATE'}</span></div><p>SKU {drop.sku} <span>·</span> detected {new Date(drop.detected_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</p><div className="drop-price-flow"><span>{money(drop.old_price)}</span><ArrowRight size={14} /><b>{money(drop.new_price)}</b><span className="drop-pct">−{drop.drop_percentage.toFixed(1)}%</span></div></div><div className="drop-delta"><span>PRICE CHANGE</span><b>−{money(drop.drop_amount)}</b></div><div className="drop-action">{drop.processed ? <span className="processed-chip"><Check size={14} /> Processed</span> : <button className="button button-accent small-button" onClick={() => process(drop)} disabled={running === drop.id}>{running === drop.id ? <LoaderCircle size={15} className="spin" /> : <Sparkles size={15} />} Evaluate buyers</button>}</div></article>)}</div>}
    <div className="review-note"><ShieldCheck size={17} /><span>DropBack evaluates eligibility and savings first. <b>Refunds are never sent until you approve a recommendation.</b></span></div>
  </>
}

function DecisionsPage({ toast }: { toast: (value: Toast) => void }) {
  const { decisions, refresh } = useWorkspaceData()
  const [working, setWorking] = useState('')
  const [quick, setQuick] = useState('')
  async function action(row: Decision, kind: 'approve' | 'reject') {
    setWorking(row.id)
    try {
      const response = await api<{ can_execute: boolean; sample_order: boolean }>(`/agent/decisions/${row.id}/${kind}`, { method: 'POST' })
      if (kind === 'approve' && response.can_execute) {
        const result = await api<{ status: string; refund_id: string; amount: number }>(`/refunds/${row.id}/execute`, { method: 'POST' })
        toast({ kind: 'success', message: `PayPal refund ${result.status.toLowerCase()}: ${money(result.amount)}.` })
      } else if (kind === 'approve' && response.sample_order) {
        toast({ kind: 'info', message: 'Sample recommendation approved for review. Sample orders cannot issue a PayPal refund.' })
      } else toast({ kind: 'success', message: kind === 'approve' ? 'Recommendation approved.' : 'Recommendation rejected.' })
      await refresh()
    } catch (error) { toast({ kind: 'error', message: error instanceof Error ? error.message : 'Action failed.' }); await refresh() }
    finally { setWorking('') }
  }
  const columns = useMemo<ColDef<Decision>[]>(() => [
    { field: 'paypal_order_id', headerName: 'ORDER / BUYER', flex: 1.2, minWidth: 160, cellRenderer: (p: { data: Decision }) => <div className="grid-buyer"><b>{p.data.buyer_name || 'Sample buyer'}</b><span>{p.data.paypal_order_id ? `#${p.data.paypal_order_id.slice(-8)}` : `#${p.data.order_id.slice(0, 8)}`}</span></div> },
    { field: 'product_name', headerName: 'PRODUCT', flex: 1.3, minWidth: 160 },
    { field: 'refund_amount', headerName: 'REFUND', flex: 0.8, minWidth: 100, valueFormatter: p => money(p.value, p.data?.currency) },
    { field: 'return_probability', headerName: 'RETURN RISK', flex: 1.2, minWidth: 150, cellRenderer: (p: { value: number }) => <RiskBar probability={p.value || 0} /> },
    { field: 'estimated_savings', headerName: 'NET SAVINGS', flex: 0.8, minWidth: 110, valueFormatter: p => money(p.value, p.data?.currency), cellClass: 'savings-cell' },
    { field: 'status', headerName: 'STATUS', flex: 0.9, minWidth: 125, cellRenderer: (p: { value: string }) => <span className={`decision-status ${p.value.toLowerCase().replace('_', '-')}`}>{p.value.replace('_', ' ')}</span> },
    { headerName: 'ACTION', flex: 1.2, minWidth: 185, sortable: false, cellRenderer: (p: { data: Decision }) => p.data.status === 'PENDING_REVIEW' ? <div className="grid-actions"><button className="approve-button" disabled={working === p.data.id} onClick={() => action(p.data, 'approve')}><Check size={14} /> Approve</button><button className="reject-button" disabled={working === p.data.id} onClick={() => action(p.data, 'reject')}>Reject</button></div> : p.data.status === 'APPROVED' && p.data.can_execute ? <span className="decision-status approved">APPROVED · SENT</span> : <span className="grid-muted">{p.data.status === 'SKIPPED' ? 'Policy skip' : p.data.status}</span> },
  ], [working])
  const awaiting = decisions.filter(row => row.status === 'PENDING_REVIEW')
  const finished = decisions.filter(row => row.status !== 'PENDING_REVIEW')
  return <>
    <PageHeading eyebrow="HUMAN-IN-THE-LOOP" title="Agent review" description="Review the reasoning and projected savings before deciding what to send back." right={<button className="button button-light" onClick={() => void refresh()}><RefreshCw size={15} /> Refresh decisions</button>} />
    <div className="review-banner"><div className="review-banner-icon"><LockKeyhole size={18} /></div><div><b>You’re in control of every refund.</b><span>Recommendations can be approved or rejected here. Only captured PayPal sandbox orders can produce a payment action.</span></div><div className="review-banner-count"><b>{awaiting.length}</b><span>awaiting you</span></div></div>
    <section className="section-block grid-section"><div className="section-head"><div><div className="section-title">Awaiting review <span className="count-bubble">{awaiting.length}</span></div><p>Deterministic policy checks plus return-likelihood scoring.</p></div><div className="grid-tools"><div className="search-field"><Search size={15} /><input value={quick} placeholder="Search recommendations" onChange={event => setQuick(event.target.value)} /></div></div></div>
      {awaiting.length ? <div className="table-frame"><div className="ag-theme-quartz grid-wrap decision-grid"><Suspense fallback={<div className="grid-loading">Preparing review table…</div>}><GridTable rowData={awaiting} columnDefs={columns} quickFilterText={quick} pagination paginationPageSize={10} /></Suspense></div></div> : <EmptyState compact icon={<Sparkles size={18} />} title="Nothing to review right now" copy="Process a Channel3 price drop to find eligible orders and create agent recommendations." action={<Link className="button button-light small-button" to="/price-drops">Open price drops <ArrowRight size={14} /></Link>} />}
    </section>
    {finished.length > 0 && <section className="section-block grid-section"><div className="section-head"><div><div className="section-title">Decision history</div><p>Approved, rejected, and policy-skipped recommendations.</p></div></div><div className="table-frame"><div className="ag-theme-quartz grid-wrap"><Suspense fallback={<div className="grid-loading">Preparing history table…</div>}><GridTable rowData={finished} columnDefs={columns} pagination paginationPageSize={10} /></Suspense></div></div></section>}
  </>
}

function RiskBar({ probability }: { probability: number }) {
  const percent = Math.round(probability * 100)
  return <div className="risk-bar-wrap"><div className="risk-bar"><i style={{ width: `${percent}%` }} /></div><span>{percent}%</span></div>
}

function OrdersPage() {
  const { orders, loading, refresh } = useWorkspaceData()
  const [quick, setQuick] = useState('')
  const columns = useMemo<ColDef<Order>[]>(() => [
    ...orderColumns,
    { field: 'source', headerName: 'SOURCE', flex: 0.7, minWidth: 95, cellRenderer: (p: { value: string }) => <span className={`source-label ${p.value === 'paypal' ? 'channel' : 'manual'}`}>{p.value === 'paypal' ? 'PAYPAL' : 'SAMPLE'}</span> },
    { headerName: 'PROTECTION', flex: 0.9, minWidth: 120, cellRenderer: (p: { data: Order }) => <span className={`order-status ${p.data.refundable ? 'complete' : 'pending'}`}><i />{p.data.refundable ? 'Refundable' : 'Sample only'}</span> },
  ], [])
  return <><PageHeading eyebrow="CUSTOMER ACTIVITY" title="Orders" description="Captured orders with their original purchase prices and protection status." right={<button className="button button-light" onClick={() => void refresh()}><RefreshCw size={15} /> Refresh</button>} />
    <div className="orders-summary"><div><span>ALL ORDERS</span><b>{orders.length}</b></div><div><span>IN PROTECTION WINDOW</span><b>{orders.filter(order => order.captured_at && (Date.now() - new Date(order.captured_at).getTime()) < 14 * 86400000).length}</b></div><div><span>PAYPAL CAPTURES</span><b>{orders.filter(order => order.refundable).length}</b></div><div className="summary-help"><ShieldCheck size={17} /><span>Sample orders help you explore the workflow. They can’t be refunded.</span></div></div>
    <div className="section-head orders-head"><div><div className="section-title">Order history</div><p>{loading ? 'Refreshing…' : 'Search captured orders and inspect buyer protection status.'}</p></div><div className="search-field"><Search size={15} /><input placeholder="Search orders" value={quick} onChange={e => setQuick(e.target.value)} /></div></div>
    <div className="table-frame"><div className="ag-theme-quartz grid-wrap order-grid"><Suspense fallback={<div className="grid-loading">Preparing order table…</div>}><GridTable rowData={orders} columnDefs={columns} quickFilterText={quick} pagination paginationPageSize={12} /></Suspense></div></div>
  </>
}

function SettingsPage({ toast }: { toast: (value: Toast) => void }) {
  const [values, setValues] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [health, setHealth] = useState<{ paypal_configured: boolean; channel3_configured: boolean; channel3_webhook_configured: boolean; paypal_environment: string } | null>(null)
  useEffect(() => {
    Promise.all([getSettings(), api<{ paypal_configured: boolean; channel3_configured: boolean; channel3_webhook_configured: boolean; paypal_environment: string }>('/health')]).then(([v, h]) => { setValues(v); setHealth(h) }).catch(() => undefined).finally(() => setLoading(false))
  }, [])
  function field(key: string, value: string | number) { setValues((current: Record<string, any>) => ({ ...current, [key]: value })) }
  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true)
    try {
      const payload = { ...values }
      delete payload.channel3_configured; delete payload.paypal_environment; delete payload.auto_refund_enabled
      await api('/settings', { method: 'PATCH', body: JSON.stringify(payload) })
      toast({ kind: 'success', message: 'Merchant settings saved.' })
    } catch (error) { toast({ kind: 'error', message: error instanceof Error ? error.message : 'Settings were not saved.' }) }
    finally { setSaving(false) }
  }
  return <><PageHeading eyebrow="PREFERENCES & CONNECTIONS" title="Settings" description="Set your protection policy and see which services are connected." />
    <div className="settings-layout"><div className="settings-main"><form onSubmit={save}>
      <section className="settings-card"><div className="settings-card-head"><div className="settings-icon"><Settings2 size={18} /></div><div><h2>Protection policy</h2><p>Set the guardrails the agent uses for every recommendation.</p></div></div><div className="settings-fields"><label>Merchant display name<input value={values.merchant_name || ''} onChange={e => field('merchant_name', e.target.value)} /></label><label>Price protection window <span className="input-suffix"><input type="number" min="1" max="90" value={values.price_protection_window_days || 14} onChange={e => field('price_protection_window_days', Number(e.target.value))} /><i>days</i></span></label><label>Maximum refund per order <span className="input-prefix"><i>$</i><input type="number" min="1" step="0.01" value={values.max_refund_per_order || 100} onChange={e => field('max_refund_per_order', Number(e.target.value))} /></span></label><label>Daily refund budget <span className="input-prefix"><i>$</i><input type="number" min="1" step="0.01" value={values.daily_refund_budget || 500} onChange={e => field('daily_refund_budget', Number(e.target.value))} /></span></label><label>Minimum price drop <span className="input-prefix"><i>$</i><input type="number" min="0" step="0.01" value={values.min_price_drop_amount || 5} onChange={e => field('min_price_drop_amount', Number(e.target.value))} /></span></label><label>Minimum percentage drop <span className="input-suffix"><input type="number" min="0" max="100" step="0.1" value={values.min_price_drop_percentage || 5} onChange={e => field('min_price_drop_percentage', Number(e.target.value))} /><i>%</i></span></label></div></section>
      <section className="settings-card"><div className="settings-card-head"><div className="settings-icon pale-orange"><RotateCcw size={18} /></div><div><h2>Return cost estimate</h2><p>Used to compare an early refund with a full return.</p></div></div><div className="settings-fields"><label>Shipping per leg <span className="input-prefix"><i>$</i><input type="number" min="0" step="0.01" value={values.return_shipping_cost || 12} onChange={e => field('return_shipping_cost', Number(e.target.value))} /></span></label><label>Restocking loss <span className="input-suffix"><input type="number" min="0" max="100" step="0.1" value={values.restocking_fee_percentage || 15} onChange={e => field('restocking_fee_percentage', Number(e.target.value))} /><i>%</i></span></label><label>Open-box discount <span className="input-suffix"><input type="number" min="0" max="100" step="0.1" value={values.open_box_discount_percentage || 25} onChange={e => field('open_box_discount_percentage', Number(e.target.value))} /><i>%</i></span></label></div></section>
      <div className="settings-save"><span><LockKeyhole size={14} /> Every refund still needs your approval.</span><button className="button button-dark" disabled={saving || loading}>{saving ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}{saving ? 'Saving…' : 'Save settings'}</button></div>
    </form></div><aside className="settings-side"><div className="settings-card connection-card"><div className="settings-card-head"><div className="settings-icon pale-green"><Activity size={18} /></div><div><h2>Connections</h2><p>Server-side service health</p></div></div><ServiceStatus name="Channel3" detail="Required live product matching & price monitoring" connected={!!health?.channel3_configured} critical /><ServiceStatus name="PayPal" detail={`${health?.paypal_environment || 'Sandbox'} checkout, capture & refunds`} connected={!!health?.paypal_configured} /><div className="setup-note"><b>{health?.channel3_configured ? 'Channel3 API connected' : 'Channel3 is required'}</b><p>{health?.channel3_configured ? health.channel3_webhook_configured ? 'Live price checks and signed webhook verification are configured.' : <>Live price checks and product subscriptions are active. To receive ongoing price-change events, set <code>CHANNEL3_WEBHOOK_SECRET</code> and register the public HTTPS endpoint shown in the README.</> : <>Live price checks require <code>CHANNEL3_API_KEY</code> on the backend. Configure it and restart the API.</>}</p></div><div className="setup-note setup-note-blue"><b>PayPal checkout testing</b><p>Sign in to the checkout popup with a Personal sandbox account from PayPal Developer Dashboard → Sandbox → Accounts.</p></div></div><div className="settings-card scoring-card"><div className="settings-card-head"><div className="settings-icon pale-purple"><Sparkles size={18} /></div><div><h2>Agent scoring</h2><p>Decision support, not autonomous payment.</p></div></div><div className="scoring-row"><span>Model assisted</span><b>When API is configured</b></div><div className="scoring-row"><span>Policy authority</span><b>Deterministic rules</b></div><div className="scoring-row"><span>Auto-refunds</span><b className="disabled-label">Disabled</b></div></div></aside></div>
  </>
}

function ServiceStatus({ name, detail, connected, critical = false }: { name: string; detail: string; connected: boolean; critical?: boolean }) {
  return <div className="service-row"><div className="service-logo">{name === 'PayPal' ? <span className="paypal-logo">P</span> : <span className="channel3-logo">3</span>}</div><div className="service-copy"><b>{name}</b><span>{detail}</span></div><span className={`service-pill ${connected ? 'is-connected' : 'is-missing'}`}><i />{connected ? 'Connected' : critical ? 'Required' : 'Missing'}</span></div>
}

function EmptyState({ icon, title, copy, action, compact = false }: { icon: ReactNode; title: string; copy: string; action?: ReactNode; compact?: boolean }) {
  return <div className={`empty-state ${compact ? 'empty-compact' : ''}`}><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{copy}</p>{action && <div>{action}</div>}</div>
}

function Storefront({ publicMode = false, toast }: { publicMode?: boolean; toast: (value: Toast) => void }) {
  const [products, setProducts] = useState<Product[]>([])
  const [config, setConfig] = useState<{ configured: boolean; client_id: string | null; environment: string } | null>(null)
  const [cart, setCart] = useState<Record<string, number>>({})
  const [payReady, setPayReady] = useState(false)
  const [eligible, setEligible] = useState(false)
  const [checkingSdk, setCheckingSdk] = useState(true)
  const [paymentMessage, setPaymentMessage] = useState('')
  const payButtonRef = useRef<HTMLButtonElement>(null)
  const pendingInternalOrderIdRef = useRef('')
  const sessionRef = useRef<{ start: (options: { presentationMode: 'auto' }, order: Promise<{ orderId: string }>) => Promise<void> } | null>(null)
  const totalCount = Object.values(cart).reduce((sum, count) => sum + count, 0)
  const total = products.reduce((sum, product) => sum + product.current_price * (cart[product.id] || 0), 0)

  useEffect(() => {
    Promise.all([getProducts(), api<{ configured: boolean; client_id: string | null; environment: string }>('/paypal/config')])
      .then(([items, settings]) => { setProducts(items); setConfig(settings) })
      .catch(() => toast({ kind: 'error', message: 'Storefront data could not be loaded.' }))
  }, [toast])

  useEffect(() => {
    if (!config?.configured || !config.client_id) { setCheckingSdk(false); return }
    let script = document.querySelector<HTMLScriptElement>('script[data-paypal-v6]')
    let mounted = true
    const setup = async () => {
      if (!script) {
        script = document.createElement('script')
        script.src = config.environment === 'sandbox' ? 'https://www.sandbox.paypal.com/web-sdk/v6/core' : 'https://www.paypal.com/web-sdk/v6/core'
        script.async = true
        script.dataset.paypalV6 = 'true'
        document.body.appendChild(script)
      }
      if (!window.paypal) await new Promise<void>((resolve, reject) => {
        script!.addEventListener('load', () => resolve(), { once: true })
        script!.addEventListener('error', () => reject(new Error('PayPal Checkout could not load.')), { once: true })
        if (window.paypal) resolve()
      })
      const sdk = await window.paypal!.createInstance({ clientId: config.client_id!, components: ['paypal-payments'], pageType: 'checkout' })
      const methods = await sdk.findEligibleMethods({ currencyCode: 'USD' })
      if (!mounted) return
      setEligible(methods.isEligible('paypal'))
      sessionRef.current = sdk.createPayPalOneTimePaymentSession({
        onApprove: async data => {
          setPaymentMessage('Payment approved — confirming your order…')
          const capture = await api<{ status: string; amount: number; currency: string }>(`/orders/${data.orderId}/capture`, { method: 'POST' })
          setPaymentMessage(`Your order is confirmed. ${money(capture.amount, capture.currency)} was captured in PayPal Sandbox.`)
          pendingInternalOrderIdRef.current = ''
          setCart({})
        },
        onCancel: () => {
          const internalOrderId = pendingInternalOrderIdRef.current
          if (internalOrderId) void api(`/orders/${internalOrderId}/cancel`, { method: 'POST' }).catch(() => undefined)
          setPaymentMessage('Checkout was cancelled. Your cart is still here.')
        },
        onError: error => { setPaymentMessage(error.message || 'PayPal checkout could not be completed.') },
      })
      setPayReady(true)
    }
    setup().catch(error => setPaymentMessage(error instanceof Error ? error.message : 'PayPal checkout could not be initialized.')).finally(() => setCheckingSdk(false))
    return () => { mounted = false }
  }, [config])

  useEffect(() => {
    const button = payButtonRef.current
    if (!button || !payReady || !sessionRef.current) return
    const click = async () => {
      if (!totalCount) return
      setPaymentMessage('Opening secure PayPal checkout…')
      const order = (async () => {
        const items = Object.entries(cart).filter(([, quantity]) => quantity > 0).map(([product_id, quantity]) => ({ product_id, quantity }))
        const created = await api<{ order_id: string; internal_order_id: string }>('/orders', { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ items }) })
        pendingInternalOrderIdRef.current = created.internal_order_id
        return { orderId: created.order_id }
      })()
      try { await sessionRef.current!.start({ presentationMode: 'auto' }, order) }
      catch (error) { setPaymentMessage(error instanceof Error ? error.message : 'Could not start PayPal checkout.') }
    }
    button.addEventListener('click', click)
    return () => button.removeEventListener('click', click)
  }, [payReady, cart, totalCount])

  return <div className="store-page">
    <header className="store-header"><Link to={publicMode ? '/login' : '/'} className="store-brand"><BrandMark /><span>HOLLOWAY<small>GOODS FOR GOOD DAYS</small></span></Link><div className="store-header-center">A little more considered.</div><div className="store-header-right"><span className="store-shipping">Complimentary shipping over $100</span><button className="cart-button" onClick={() => document.getElementById('store-cart')?.scrollIntoView({ behavior: 'smooth' })}><ShoppingBag size={17} /><b>{totalCount}</b></button></div></header>
    <section className="store-hero"><div className="store-hero-copy"><span className="store-kicker"><span /> CAREFULLY CHOSEN, MADE TO LAST</span><h1>Good things,<br /><em>for everyday.</em></h1><p>Thoughtful pieces for a slower morning, a clearer commute, and everything in between.</p><a href="#catalog" className="button button-dark">Explore the collection <ArrowRight size={16} /></a><div className="store-trust"><ShieldCheck size={15} /> Covered by DropBack price protection for 14 days.</div></div><div className="store-hero-art"><div className="hero-sun" /><div className="hero-product"><span>☕</span><i /></div><div className="hero-caption"><b>01 / MORNING RITUAL</b><span>Made to be used every day</span></div><div className="hero-decoration decor-one" /><div className="hero-decoration decor-two" /></div></section>
    <section id="catalog" className="store-catalog"><div className="store-section-title"><div><span>THE HOLLOWAY EDIT</span><h2>Made for the everyday</h2></div><span>03 OBJECTS <i /> CONSIDERED</span></div><div className="store-products">{products.map((product, i) => <article className="store-product" key={product.id}><div className={`store-product-art art-${i % 3}`}><span>{i === 0 ? '☕' : i === 1 ? '◉' : '▱'}</span><label>14-DAY PRICE COVER</label><button className="quick-add" onClick={() => setCart(current => ({ ...current, [product.id]: (current[product.id] || 0) + 1 }))}><Plus size={17} /></button></div><div className="store-product-detail"><div><span>{product.category.toUpperCase()}</span><h3>{product.name}</h3><p>{product.description}</p></div><strong>{money(product.current_price, product.currency)}</strong></div><button className="add-cart-button" onClick={() => setCart(current => ({ ...current, [product.id]: (current[product.id] || 0) + 1 }))}>{cart[product.id] ? <>Add another <span>· {cart[product.id]} in bag</span></> : <>Add to bag <Plus size={15} /></>}</button></article>)}</div></section>
    <section className="store-protection"><div className="protection-mark"><ShieldCheck size={26} /></div><div><span>OUR LITTLE PROMISE</span><h2>We watch the price, so you don’t have to.</h2><p>If something you bought drops in price within 14 days, we’ll send back the difference. It’s the kind of thing we think should just happen.</p></div><div className="protection-stat"><b>14</b><span>DAYS OF<br />PRICE COVER</span></div></section>
    <section className="store-checkout" id="store-cart"><div className="checkout-left"><span className="store-kicker">YOUR BAG <b>{totalCount.toString().padStart(2, '0')}</b></span><h2>Ready when you are.</h2><p>Take your good things home. We’ll keep watch on the price.</p>{totalCount > 0 ? <div className="cart-lines">{products.filter(product => cart[product.id]).map(product => <div className="cart-line" key={product.id}><span>{product.name} <i>× {cart[product.id]}</i></span><b>{money(product.current_price * cart[product.id], product.currency)}</b><button onClick={() => setCart(current => ({ ...current, [product.id]: Math.max(0, (current[product.id] || 0) - 1) }))} aria-label={`Remove one ${product.name}`}><X size={14} /></button></div>)}<div className="cart-total"><span>Total</span><b>{money(total)}</b></div></div> : <p className="cart-empty">Your bag is waiting for something good.</p>}</div><div className="checkout-right"><div className="checkout-total"><span>ORDER TOTAL</span><b>{money(total)}</b><small>Shipping and taxes calculated at checkout.</small></div><button ref={payButtonRef} className={`paypal-checkout-button ${!payReady || !eligible || !totalCount ? 'is-disabled' : ''}`} disabled={!payReady || !eligible || !totalCount} type="button"><span className="paypal-word">Pay<span>Pal</span></span><span>{checkingSdk ? 'Preparing secure checkout…' : eligible ? 'Continue with PayPal' : 'PayPal checkout unavailable'}</span><ArrowRight size={17} /></button>{!config?.configured && <div className="checkout-notice">Set PayPal sandbox credentials in the backend environment to enable live checkout.</div>}{paymentMessage && <div className="payment-message" role="status">{paymentMessage}</div>}<div className="checkout-lock"><LockKeyhole size={13} /> Encrypted PayPal Sandbox checkout</div></div></section>
    <footer className="store-footer"><span>HOLLOWAY GOODS</span><span>Made with care. Covered by DropBack.</span><Link to={publicMode ? '/login' : '/'}>Merchant console <ArrowRight size={14} /></Link></footer>
  </div>
}

function CheckoutStatus({ success }: { success: boolean }) {
  return <div className="checkout-status-page"><div className={`checkout-status-icon ${success ? 'green' : 'orange'}`}>{success ? <CheckCircle2 size={26} /> : <X size={26} />}</div><div className="eyebrow">HOLLOWAY GOODS</div><h1>{success ? 'You’re all set.' : 'Your bag is still here.'}</h1><p>{success ? 'We’ll keep an eye on your price for the next 14 days.' : 'Checkout was cancelled. Pick up where you left off when you’re ready.'}</p><Link to="/store" className="button button-dark">Back to the storefront <ArrowRight size={16} /></Link></div>
}

export default App
