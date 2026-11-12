import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, Check, Copy, KeyRound, LoaderCircle, Package, Rocket, ShieldCheck, Store, Webhook } from 'lucide-react'
import { api, getSettings } from './api'

type Toast = { message: string; kind: 'success' | 'error' | 'info' }

export type SetupOverview = {
  store: { merchant_name: string; store_url: string; gross_margin_percentage: number; owner_email: string | null }
  paypal: { connected: boolean; source: 'merchant' | 'env' | 'none'; environment: string; client_id: string | null; connected_at: string | null
    webhook_url: string; webhook_registered: boolean; webhook_events: string[] }
  policy: { price_protection_window_days: number; max_refund_per_order: number; daily_refund_budget: number; allowed_retailers: string[] }
  catalog: { products: number; linked: number }
  orders: { protected: number; imported: number }
  install: { portal_url: string; store_url: string; email_snippet: string }
  completed: boolean
}

export const getSetup = () => api<SetupOverview>('/setup')

const STEPS = [
  { id: 'store', label: 'Your store', icon: Store },
  { id: 'paypal', label: 'Connect PayPal', icon: KeyRound },
  { id: 'policy', label: 'Protection policy', icon: ShieldCheck },
  { id: 'catalog', label: 'Products to protect', icon: Package },
  { id: 'live', label: 'Go live', icon: Rocket },
] as const
type StepId = typeof STEPS[number]['id']

export default function SetupPage({ toast }: { toast: (value: Toast) => void }) {
  const navigate = useNavigate()
  const [setup, setSetup] = useState<SetupOverview | null>(null)
  const [step, setStep] = useState<StepId>('store')
  const [busy, setBusy] = useState(false)
  const [store, setStore] = useState({ merchant_name: '', store_url: '', gross_margin_percentage: 30 })
  const [policy, setPolicy] = useState({ price_protection_window_days: 14, max_refund_per_order: 100, daily_refund_budget: 500, allowed_retailers: '' })
  const [creds, setCreds] = useState({ client_id: '', client_secret: '' })
  const [importId, setImportId] = useState('')

  const load = useCallback(async () => {
    const [overview, settings] = await Promise.all([getSetup(), getSettings()])
    setSetup(overview)
    setStore({ merchant_name: overview.store.merchant_name, store_url: overview.store.store_url, gross_margin_percentage: overview.store.gross_margin_percentage })
    setPolicy({ price_protection_window_days: Number(settings.price_protection_window_days), max_refund_per_order: Number(settings.max_refund_per_order),
      daily_refund_budget: Number(settings.daily_refund_budget), allowed_retailers: (settings.allowed_retailers as string[] || []).join(', ') })
    return overview
  }, [])

  useEffect(() => { void load().catch(() => toast({ kind: 'error', message: 'Could not load your setup.' })) }, [load])

  const done: Record<StepId, boolean> = {
    store: !!setup && setup.store.merchant_name !== 'DropBack Demo Store',
    paypal: setup?.paypal.source === 'merchant',
    policy: !!setup && (setup.completed || setup.policy.allowed_retailers.length > 0),
    catalog: !!setup && setup.catalog.products > 0,
    live: !!setup?.completed,
  }

  async function run(action: () => Promise<unknown>, success: string, next?: StepId): Promise<boolean> {
    setBusy(true)
    try {
      await action()
      await load()
      toast({ kind: 'success', message: success })
      if (next) setStep(next)
      return true
    } catch (error) {
      toast({ kind: 'error', message: error instanceof Error ? error.message : 'That did not work. Try again.' })
      return false
    } finally { setBusy(false) }
  }

  const saveStore = (event: FormEvent) => { event.preventDefault(); void run(() => api('/settings', { method: 'PATCH', body: JSON.stringify(store) }), 'Store details saved.', 'paypal') }
  const savePolicy = (event: FormEvent) => { event.preventDefault(); void run(() => api('/settings', { method: 'PATCH', body: JSON.stringify(policy) }), 'Protection policy saved.', 'catalog') }
  const connect = (event: FormEvent) => {
    event.preventDefault()
    void run(async () => {
      await api('/setup/paypal', { method: 'POST', body: JSON.stringify(creds) })
      setCreds({ client_id: '', client_secret: '' })
    }, 'PayPal connected. DropBack now refunds from your PayPal account.')
  }
  const importOrder = (event: FormEvent) => {
    event.preventDefault()
    void run(() => api('/orders/import', { method: 'POST', body: JSON.stringify({ paypal_order_id: importId.trim() }) }), 'Order imported and protected.')
  }
  const finish = () => void run(() => api('/setup/complete', { method: 'POST' }), 'DropBack is live for your store.').then(ok => { if (ok) navigate('/') })
  const linkCatalog = () => void run(async () => {
    const products = await api<{ id: string }[]>('/products')
    for (const product of products) await api(`/products/${product.id}/channel3-check`, { method: 'POST' }).catch(() => undefined)
  }, 'Products linked to live Channel3 listings.')
  const copy = (text: string) => { void navigator.clipboard?.writeText(text); toast({ kind: 'info', message: 'Copied.' }) }

  if (!setup) return <div className="setup-loading"><LoaderCircle className="spin" size={18} /> Loading your setup…</div>

  return <div className="setup-page" data-testid="setup-page">
    <div className="page-heading"><div><div className="eyebrow">MERCHANT ONBOARDING</div><h1>Set up DropBack for {setup.store.merchant_name}</h1>
      <p>Keep your PayPal checkout. DropBack connects to it, watches prices for what you sell, and refunds the difference when you approve.</p></div></div>
    <div className="setup-layout">
      <ol className="setup-steps">
        {STEPS.map((item, index) => <li key={item.id}>
          <button type="button" data-testid={`setup-step-${item.id}`} className={`setup-step ${step === item.id ? 'active' : ''} ${done[item.id] ? 'done' : ''}`} onClick={() => setStep(item.id)}>
            <span className="setup-step-mark">{done[item.id] ? <Check size={14} /> : index + 1}</span>
            <span>{item.label}</span>
          </button>
        </li>)}
      </ol>

      <section className="settings-card setup-panel">
        {step === 'store' && <form onSubmit={saveStore}>
          <PanelHead icon={<Store size={18} />} title="Your store" copy="The name buyers see on refunds, and the profit you lose when a buyer returns an item to buy it elsewhere." />
          <div className="settings-fields">
            <label>Store name<input data-testid="setup-store-name" required value={store.merchant_name} onChange={e => setStore({ ...store, merchant_name: e.target.value })} /></label>
            <label>Store website<input data-testid="setup-store-url" placeholder="https://yourstore.com" value={store.store_url} onChange={e => setStore({ ...store, store_url: e.target.value })} /></label>
            <label>Gross margin <span className="input-suffix"><input type="number" min="0" max="100" step="0.5" value={store.gross_margin_percentage} onChange={e => setStore({ ...store, gross_margin_percentage: Number(e.target.value) })} /><i>%</i></span></label>
          </div>
          <PanelActions busy={busy} label="Save and continue" />
        </form>}

        {step === 'paypal' && <div>
          <PanelHead icon={<KeyRound size={18} />} title="Connect your PayPal account" copy="Paste the REST app credentials from developer.paypal.com → Apps & Credentials. DropBack verifies them with PayPal, encrypts the secret, and runs every order lookup and refund as your account." />
          <div className={`setup-status ${setup.paypal.source === 'merchant' ? 'ok' : setup.paypal.source === 'env' ? 'warn' : 'missing'}`} data-testid="setup-paypal-status">
            {setup.paypal.source === 'merchant' ? <><Check size={15} /> Connected: your PayPal app {setup.paypal.client_id} ({setup.paypal.environment})</>
              : setup.paypal.source === 'env' ? <>Using the server's demo PayPal app {setup.paypal.client_id}. Connect your own to receive payments and send refunds from your account.</>
              : <>Not connected yet.</>}
          </div>
          <form className="settings-fields" onSubmit={connect}>
            <label>Client ID<input data-testid="setup-paypal-client-id" required autoComplete="off" value={creds.client_id} onChange={e => setCreds({ ...creds, client_id: e.target.value })} /></label>
            <label>Secret<input data-testid="setup-paypal-secret" required type="password" autoComplete="off" value={creds.client_secret} onChange={e => setCreds({ ...creds, client_secret: e.target.value })} /></label>
            <div className="setup-inline-actions"><button className="button button-dark" data-testid="setup-paypal-connect" disabled={busy}>{busy ? <LoaderCircle size={15} className="spin" /> : <KeyRound size={15} />} Verify and connect</button>
              {setup.paypal.source === 'merchant' && <button type="button" className="button button-light" onClick={() => setStep('policy')}>Continue <ArrowRight size={15} /></button>}</div>
          </form>
          <div className="setup-note setup-note-blue setup-webhook"><b><Webhook size={14} /> How orders reach DropBack</b>
            <p>{setup.paypal.webhook_registered ? 'Registered with PayPal: ' : 'Webhook endpoint: '}<code>{setup.paypal.webhook_url}</code>. Every completed PayPal payment ({setup.paypal.webhook_events[0]}) is imported automatically.
              {!setup.paypal.webhook_registered && ' PayPal only delivers to public HTTPS URLs, so on a local install buyers bring their order in themselves: the protection portal imports any PayPal order paid to your account.'}</p>
          </div>
          <form className="setup-import" onSubmit={importOrder}>
            <label>Test it: import a PayPal order ID<input data-testid="setup-import-id" placeholder="e.g. 5O190127TN364715T" value={importId} onChange={e => setImportId(e.target.value)} /></label>
            <button className="button button-light" disabled={busy || importId.trim().length < 8}>Import order</button>
            <span className="muted">{setup.orders.protected} protected order{setup.orders.protected === 1 ? '' : 's'} · {setup.orders.imported} imported from PayPal</span>
          </form>
        </div>}

        {step === 'policy' && <form onSubmit={savePolicy}>
          <PanelHead icon={<ShieldCheck size={18} />} title="Protection policy" copy="Hard limits enforced in code. The AI recommends; it never overrides these, and every refund still needs your approval." />
          <div className="settings-fields">
            <label>Protection window <span className="input-suffix"><input type="number" min="1" max="90" value={policy.price_protection_window_days} onChange={e => setPolicy({ ...policy, price_protection_window_days: Number(e.target.value) })} /><i>days</i></span></label>
            <label>Max refund per order <span className="input-prefix"><i>$</i><input type="number" min="1" step="0.01" value={policy.max_refund_per_order} onChange={e => setPolicy({ ...policy, max_refund_per_order: Number(e.target.value) })} /></span></label>
            <label>Daily refund budget <span className="input-prefix"><i>$</i><input type="number" min="1" step="0.01" value={policy.daily_refund_budget} onChange={e => setPolicy({ ...policy, daily_refund_budget: Number(e.target.value) })} /></span></label>
            <label className="full-field">Retailers you price-match <input data-testid="setup-retailers" placeholder="bestbuy.com, target.com, beachcamera.com (empty = any in-stock new offer)" value={policy.allowed_retailers} onChange={e => setPolicy({ ...policy, allowed_retailers: e.target.value })} /></label>
          </div>
          <p className="muted setup-hint">Only new, in-stock offers for the exact model count. One price-match claim per order.</p>
          <PanelActions busy={busy} label="Save policy" />
        </form>}

        {step === 'catalog' && <div>
          <PanelHead icon={<Package size={18} />} title="Products to protect" copy="Add what you sell from the live Channel3 catalog. Orders are matched to products by SKU, or by name when the SKU differs." />
          <div className={`setup-status ${setup.catalog.linked ? 'ok' : setup.catalog.products ? 'warn' : 'missing'}`}>{setup.catalog.linked ? <><Check size={15} /> {setup.catalog.linked} of {setup.catalog.products} products linked for price monitoring</> : setup.catalog.products ? `${setup.catalog.products} products in your catalog, not yet linked to Channel3. Buyers see linked products only.` : 'No products yet.'}</div>
          <div className="setup-inline-actions">{setup.catalog.linked < setup.catalog.products && <button type="button" className="button button-accent" data-testid="setup-link-catalog" disabled={busy} onClick={linkCatalog}>{busy ? <LoaderCircle size={15} className="spin" /> : <Package size={15} />} Link products with Channel3</button>}<Link className="button button-light" to="/products">Manage products</Link><button type="button" className="button button-dark" onClick={() => setStep('live')}>Continue <ArrowRight size={15} /></button></div>
        </div>}

        {step === 'live' && <div>
          <PanelHead icon={<Rocket size={18} />} title="Go live" copy="Tell buyers about the guarantee. Add this line to your order-confirmation email; the link opens their protection portal." />
          <div className="setup-copy-block" data-testid="setup-email-snippet"><p>{setup.install.email_snippet}</p><button type="button" className="icon-button" onClick={() => copy(setup.install.email_snippet)} aria-label="Copy email line"><Copy size={15} /></button></div>
          <div className="setup-copy-block"><p><b>Buyer portal</b> <code>{setup.install.portal_url}</code></p><button type="button" className="icon-button" onClick={() => copy(setup.install.portal_url)} aria-label="Copy portal link"><Copy size={15} /></button></div>
          <ul className="setup-checklist">
            {STEPS.slice(0, 4).map(item => <li key={item.id} className={done[item.id] ? 'ok' : ''}>{done[item.id] ? <Check size={14} /> : <span className="dot" />}{item.label}</li>)}
          </ul>
          <div className="setup-inline-actions"><button type="button" className="button button-accent" data-testid="setup-finish" disabled={busy || setup.paypal.source === 'none' || !setup.catalog.products} onClick={finish}>{setup.completed ? 'Back to overview' : 'Turn on price protection'} <ArrowRight size={15} /></button></div>
        </div>}
      </section>
    </div>
  </div>
}

function PanelHead({ icon, title, copy }: { icon: ReactNode; title: string; copy: string }) {
  return <div className="settings-card-head"><div className="settings-icon pale-green">{icon}</div><div><h2>{title}</h2><p>{copy}</p></div></div>
}

function PanelActions({ busy, label }: { busy: boolean; label: string }) {
  return <div className="setup-inline-actions"><button className="button button-dark" disabled={busy}>{busy ? <LoaderCircle size={15} className="spin" /> : <Check size={15} />} {label}</button></div>
}
