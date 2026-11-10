import type { Decision, Order, PriceDrop, Product, Stats } from './types'

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
export const getStats = () => api<Stats>('/dashboard/stats')
export const getSettings = () => api<Record<string, unknown>>('/settings')

export function money(value: number, currency = 'USD') {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(value || 0)
}
