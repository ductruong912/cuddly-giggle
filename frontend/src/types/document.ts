export type ProcessingMode = 'ocr' | 'extraction'

export type DocumentType = 'pdf' | 'image' | 'office' | 'markdown' | 'unknown'

export interface UploadedDocument {
  file: File
  name: string
  size: number
  type: DocumentType
  extension: string
  previewUrl?: string
}

export interface ProcessingState {
  isProcessing: boolean
  startTime: number | null
  elapsedSeconds: number
  statusMessage: string
  abortController: AbortController | null
}

export interface OCRResult {
  mode: 'ocr'
  markdown: string
  requestTime: number
  filename: string
  elapsedSeconds: number
}

export interface ExtractionResult {
  mode: 'extraction'
  response: import('./api').LLMExtractionResponse
  requestTime: number
  filename: string
  elapsedSeconds: number
}

export type ResultData = OCRResult | ExtractionResult | null

export type BackendStatus = 'ready' | 'degraded' | 'offline' | 'checking'
