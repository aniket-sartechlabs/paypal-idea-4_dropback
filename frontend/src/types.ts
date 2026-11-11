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
  channel3_product_id?: string | null
  last_market_price?: number | null
  competitor_name?: string | null
  competitor_url?: string | null
  weight_lbs?: number | null
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
  drafted_customer_message?: string
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
  customer_claim?: boolean
  customer_notes?: string
  ai_drafted_message?: string
  merchant_message?: string
  competitor_name?: string | null
  competitor_price?: number | null
  decision: 'REFUND' | 'SKIP'
  status: string
  within_window: boolean
  budget_available: boolean
  source: string
  can_execute: boolean
  created_at: string
  reviewed_at?: string | null
}

export type RefundRecord = {
  id: string
  decision_id: string
  paypal_refund_id?: string | null
  amount: number
  currency: string
  status: string
  note_to_payer: string
  created_at: string
  completed_at?: string | null
}

export type APIMaticStatus = {
  apimatic_enabled: boolean
  version: string
  plugin_name: string
  environment: string
  sandbox_ready: boolean
  tools_count: number
  tools: { name: string; description: string; parameters: any }[]
  schemas: Record<string, any>
  last_verified: string
}

export type PriceCheckResult = {
  matched: boolean
  product_id?: string
  product_name?: string
  sku?: string
  paid_price?: number
  currency?: string
  competitor_name?: string
  competitor_price?: number
  drop_amount?: number
  drop_percentage?: number
  price_drop_detected?: boolean
  protection_active?: boolean
  best_offer?: { price: number; merchant: string; url?: string }
  all_offers?: { price: number; merchant: string; url?: string }[]
  message?: string
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
