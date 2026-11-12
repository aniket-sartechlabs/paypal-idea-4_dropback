import type { PayPalToolsStatus, Decision, Order, PriceCheckResult, PriceDrop, Product, RefundRecord, Stats } from './types'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    credentials: 'include',
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(data.detail || `Request failed (${response.status})`, response.status)
  return data as T
}

export const getProducts = () => api<Product[]>('/products')
export const getOrders = () => api<Order[]>('/orders')
export const getDrops = () => api<PriceDrop[]>('/price-drops')
export const getDecisions = () => api<Decision[]>('/agent/decisions')
export const getRefunds = () => api<RefundRecord[]>('/refunds')
export const getStats = () => api<Stats>('/dashboard/stats')
export const getSettings = () => api<Record<string, unknown>>('/settings')
export const getPayPalToolsStatus = () => api<PayPalToolsStatus>('/paypal-tools/status')
export const invokePayPalTool = (tool: string, args: Record<string, any> = {}, idempotencyKey?: string) =>
  api<any>('/paypal-tools/invoke', {
    method: 'POST',
    body: JSON.stringify({ tool, arguments: args }),
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
  })
export type BuyerOrderSummary = { id: string; paypal_order_id: string | null; status: string; item_name: string; total_amount: number; currency: string; created_at: string | null }
export const buyerLogin = (orderId: string, email: string) =>
  api<{ authenticated: boolean; order: BuyerOrderSummary }>('/buyer/login', { method: 'POST', body: JSON.stringify({ order_id: orderId, email }) })
export const getBuyerOrders = () => api<{ authenticated: boolean; orders: BuyerOrderSummary[] }>('/buyer/orders')
export const buyerLogout = () => api('/buyer/logout', { method: 'POST' })
export const lookupOrder = (key: string) => api<any>(`/orders/lookup/${encodeURIComponent(key)}`)
export const checkPriceForClaim = (payload: { order_id?: string; product_id?: string }) =>
  api<PriceCheckResult>('/claims/check-price', { method: 'POST', body: JSON.stringify(payload) })
export const submitClaim = (payload: { order_id: string; product_id?: string; price_drop_id?: string | null; customer_notes?: string; reason?: string }) =>
  api<Decision>('/claims/submit', { method: 'POST', body: JSON.stringify(payload) })
export const resolveClaim = (id: string, payload: { action: 'approve' | 'reject'; refund_amount?: number; custom_message?: string }) =>
  api<Decision>(`/claims/${id}/resolve`, { method: 'POST', body: JSON.stringify(payload) })

export function money(value: number, currency = 'USD') {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(value || 0)
}
