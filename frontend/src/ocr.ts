export interface OCRBlock {
  block_id: string
  type: string
  content: string
  bbox: { x: number; y: number }[]
  confidence: number
  page_index: number
  source_engine: string
  extra: Record<string, unknown>
}

export function blockKey(block: OCRBlock): string {
  return JSON.stringify([block.page_index, block.block_id])
}

export interface OCRTable {
  table_id: string
  page_index: number
  confidence: number
  cells: {
    row: number
    col: number
    rowspan: number
    colspan: number
    text: string
    confidence: number
  }[]
}

export interface OCRPage {
  page_index: number
  blocks: OCRBlock[]
  tables: OCRTable[]
  reading_order: string[]
  confidence: number
  source_engine: string
  geometry: {
    width: number
    height: number
    coordinate_space: string
    original?: {
      width: number
      height: number
      transform: [number, number, number, number, number, number]
    } | null
  } | null
  preview_image?: string | null
}

export interface OCRResult {
  request_id: string
  decision: { reason: string }
  pages: OCRPage[]
  blocks: OCRBlock[]
  tables: OCRTable[]
  reading_order: string[]
  markdown: string
  engine_name: string
}

export function previewImage(page: OCRPage | undefined): string | null {
  // Only server-produced inline JPEGs; never fetch an arbitrary URL from OCR JSON.
  return typeof page?.preview_image === 'string' &&
    /^data:image\/jpeg;base64,[A-Za-z0-9+/]+=*$/.test(page.preview_image)
    ? page.preview_image
    : null
}

export function canOverlay(
  page: OCRPage | undefined,
  space: 'original' | 'processed' = 'original',
): page is OCRPage {
  return (
    !!page?.geometry &&
    (space === 'processed'
      ? !!previewImage(page)
      : page.geometry.coordinate_space === 'original' || !!page.geometry.original) &&
    page.geometry.width > 0 &&
    page.geometry.height > 0 &&
    page.blocks.some((block) => block.bbox.length >= 3)
  )
}
