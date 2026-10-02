export interface HealthzResponse {
  status: string
  stages: Record<string, {
    max_concurrency: number
    active: number
    waiting: number
    abandoned: number
  }>
}

export interface ReadinessChecks {
  vl_runtime: string
  llm_credentials: string
  stages: string
  database: string
}

export interface ReadyzResponse {
  status: 'ready' | 'not_ready'
  checks: ReadinessChecks
  stages: Record<string, {
    max_concurrency: number
    active: number
    waiting: number
    abandoned: number
  }>
  degraded_stages?: string[]
}

export interface ValidationIssue {
  field: string
  message: string
  severity: string
}

export interface ExtractionValidation {
  status: 'valid' | 'needs_review' | string
  attempts: number
  healed: boolean
  issues: ValidationIssue[]
}

export interface PurchaseOrderItem {
  toto_number: string
  customer_number: string | null
  quantity: number
  unit_price: number
  extension: number | null
}

export interface PurchaseOrderData {
  po_number?: string
  po_date?: string
  items?: PurchaseOrderItem[]
  [key: string]: unknown
}

export interface LLMExtractionOCRMetadata {
  decision: string
  page_count: number
}

export interface LLMExtractionResponse {
  request_id: string
  ocr: LLMExtractionOCRMetadata
  data: PurchaseOrderData
  validation: ExtractionValidation
}

export interface ExtractionRecordItem {
  line_number: number
  toto_number: string
  customer_number: string | null
  quantity: number
  unit_price: number
  extension: number | null
}

export interface ExtractionRecord {
  id: number
  request_id: string
  source_filename: string
  route: string
  engine: string | null
  page_count: number
  po_number: string | null
  po_date: string | null
  validation_status: string
  attempts: number
  healed: boolean
  data: PurchaseOrderData
  issues: ValidationIssue[]
  markdown?: string | null
  duration_ms?: number | null
  created_at: string
  items?: ExtractionRecordItem[]
}

export interface ExtractionListResponse {
  total: number
  limit: number
  offset: number
  items: ExtractionRecord[]
}

export interface ApiErrorDetail {
  detail?: string | Array<{ msg: string; loc: string[] }>
  message?: string
}
