import type { OCRResult } from '../src/ocr'

export function ocrFixture(markdown: string): OCRResult {
  return {
    request_id: 'ocr_synthetic',
    decision: { reason: 'Synthetic OCR fixture' },
    pages: [],
    blocks: [],
    tables: [],
    reading_order: [],
    markdown,
    engine_name: 'test',
  }
}
