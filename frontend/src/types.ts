export type Product = {
  id: string
  name: string
  sku: string
  description: string
  category: string
  current_price: number
  currency: string
  protection_days: number
  merchant_domain?: string | null
  channel3_connected: boolean
  active: boolean
}

export type Order = {
  id: string
  paypal_order_id?: string | null
  status: string
  source: 'paypal' | 'sample'
  buyer_name: string
  buyer_email: string
  total_amount: number
  currency: string
  created_at: string
  captured_at?: string | null
  refundable: boolean
  items: { product_id: string | null; sku: string; name: string; quantity: number; unit_price: number }[]
}

export type PriceDrop = {
  id: string
  product_id: string
  product_name: string
  sku: string
  old_price: number
  new_price: number
  drop_amount: number
  drop_percentage: number
  source: string
  detected_at: string
  processed: boolean
}

export type AnalysisReport = {
  return_probability?: number
  confidence?: 'HIGH' | 'MEDIUM' | 'LOW' | string
  risk_level?: 'HIGH' | 'MEDIUM' | 'LOW' | string
  key_drivers?: string[]
  reasoning?: string
  retention_impact?: string
  recommended_action?: string
  provider?: string
  model?: string
  financial_breakdown?: {
    purchase_price?: number
    drop_percentage?: number
    days_since_purchase?: number
    proposed_refund?: number
    estimated_return_cost?: number
    net_savings?: number
  }
}

export type Decision = {
  id: string
  price_drop_id: string
  order_id: string
  paypal_order_id?: string | null
  buyer_name: string
  buyer_email: string
  product_name: string
  sku: string
  purchase_price: number
  refund_amount: number
  currency: string
  return_probability: number
  estimated_return_cost: number
  estimated_savings: number
  reasoning: string
  analysis_report?: AnalysisReport
  decision: 'REFUND' | 'SKIP'
  status: string
  within_window: boolean
  budget_available: boolean
  source: string
  can_execute: boolean
  created_at: string
}

export type Stats = {
  orders_exposed: number
  refunds_issued: number
  total_refunded: number
  recommendations_pending: number
  estimated_returns_avoided: number
  estimated_savings: number
  orders_total: number
  decisions_total: number
  sample_orders: number
  paypal_configured: boolean
  channel3_configured: boolean
}
