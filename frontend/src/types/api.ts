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

// =====================================================================================
// Phase 2: Document Parse & Visual Inspector Types
// =====================================================================================

export type CoordinateSpace = 'processed_image_pixels' | 'pdf_points' | 'none'

export type ConfidenceSource = 'real_engine' | 'synthesized' | 'unknown'

export type BlockType =
  | 'text'
  | 'title'
  | 'table'
  | 'figure'
  | 'header'
  | 'footer'
  | 'page_number'
  | 'caption'
  | 'equation'
  | 'code'
  | 'reference'
  | 'other'

export interface Point {
  x: number
  y: number
}

export interface PageGeometry {
  width: number
  height: number
  coordinate_space: CoordinateSpace
}

export interface PageVisual {
  available: boolean
  kind: string | null
  url: string | null
}

export interface ParseBlock {
  block_id: string
  type: BlockType
  content: string
  confidence: number
  confidence_source: ConfidenceSource
  bbox: Point[]
  bbox_normalized: Point[]
  page_index: number
  source_engine: string
  extra: Record<string, unknown>
}

export interface ParsePage {
  page_index: number
  geometry: PageGeometry
  visual: PageVisual
  blocks: ParseBlock[]
  tables: unknown[]
  reading_order: string[]
  confidence: number
}

export interface DocumentParseResponse {
  request_id: string
  decision: {
    reason: string
  }
  engine_name: string
  markdown: string | null
  pages: ParsePage[]
}

export const OCR_REVIEW_LOW_CONFIDENCE_THRESHOLD = 0.75

export function isReviewIssue(
  confidence: number,
  confidenceSource: ConfidenceSource,
  threshold: number = OCR_REVIEW_LOW_CONFIDENCE_THRESHOLD
): boolean {
  if (confidenceSource === 'real_engine') {
    return confidence < threshold
  }
  if (confidenceSource === 'unknown') {
    return true
  }
  // Synthesized is never marked as a review issue
  return false
}
