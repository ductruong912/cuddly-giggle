import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from '../App'
import { BlocksView } from '../components/extraction/BlocksView'
import { OcrInspector } from '../components/document/OcrInspector'
import { apiClient } from '../api/client'
import { OCR_REVIEW_LOW_CONFIDENCE_THRESHOLD, isReviewIssue } from '../types/api'
import type { DocumentParseResponse } from '../types/api'

// Mock apiClient
vi.mock('../api/client', () => ({
  apiClient: {
    getHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
    getReadiness: vi.fn().mockResolvedValue({
      status: 'ready',
      checks: {
        vl_runtime: 'ok',
        llm_credentials: 'ok',
        stages: 'ok',
        database: 'ok',
      },
      stages: {},
    }),
    parseDocument: vi.fn(),
    ocrDocument: vi.fn(),
    extractLocal: vi.fn(),
    getExtractions: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 }),
    getExtraction: vi.fn(),
  },
}))

const mockReviewParseResponse: DocumentParseResponse = {
  request_id: 'test-review-req-123',
  decision: { reason: 'local' },
  engine_name: 'paddleocr_vl',
  markdown: '# PHIẾU GIAO HÀNG\nĐơn giá: 500,000 đ',
  pages: [
    {
      page_index: 0,
      geometry: {
        width: 1000,
        height: 1400,
        coordinate_space: 'processed_image_pixels',
      },
      visual: {
        available: true,
        kind: 'processed_png',
        url: '/v1/doc/parse/test-review-req-123/pages/0/image',
      },
      reading_order: ['blk-1', 'blk-2', 'blk-3', 'blk-4', 'blk-5'],
      blocks: [
        {
          block_id: 'blk-1',
          type: 'text',
          content: 'Công ty TNHH Tuấn Thành cung cấp vật tư',
          confidence: 0.95,
          confidence_source: 'real_engine',
          bbox: [
            { x: 100, y: 100 },
            { x: 300, y: 100 },
            { x: 300, y: 150 },
            { x: 100, y: 150 },
          ],
          bbox_normalized: [],
          page_index: 0,
          source_engine: 'paddleocr_vl',
          extra: {},
        },
        {
          block_id: 'blk-2',
          type: 'title',
          content: 'PHIẾU XUẤT KHO KIÊM GIAO HÀNG',
          confidence: 0.65, // < 0.75 => Review Issue
          confidence_source: 'real_engine',
          bbox: [
            { x: 50, y: 50 },
            { x: 400, y: 50 },
            { x: 400, y: 90 },
            { x: 50, y: 90 },
          ],
          bbox_normalized: [],
          page_index: 0,
          source_engine: 'paddleocr_vl',
          extra: {},
        },
        {
          block_id: 'blk-3',
          type: 'table',
          content: 'Bảng kê hàng hóa danh mục số 01',
          confidence: 0.50, // 0.50 but synthesized => NOT an issue!
          confidence_source: 'synthesized',
          bbox: [
            { x: 50, y: 200 },
            { x: 600, y: 200 },
            { x: 600, y: 400 },
            { x: 50, y: 400 },
          ],
          bbox_normalized: [],
          page_index: 0,
          source_engine: 'paddleocr_vl',
          extra: {},
        },
        {
          block_id: 'blk-4',
          type: 'header',
          content: 'Mã hợp đồng kinh tế: HD-9988',
          confidence: 0.0,
          confidence_source: 'unknown', // Unknown => Review Issue!
          bbox: [
            { x: 50, y: 10 },
            { x: 250, y: 10 },
            { x: 250, y: 40 },
            { x: 50, y: 40 },
          ],
          bbox_normalized: [],
          page_index: 0,
          source_engine: 'paddleocr_vl',
          extra: {},
        },
        {
          block_id: 'blk-5',
          type: 'other',
          content: 'Ghi chú phụ lục không có khung vẽ tọa độ',
          confidence: 0.88,
          confidence_source: 'real_engine',
          bbox: [], // No bbox points!
          bbox_normalized: [],
          page_index: 0,
          source_engine: 'paddleocr_vl',
          extra: {},
        },
      ],
      tables: [],
      confidence: 0.85,
    },
    {
      page_index: 1,
      geometry: {
        width: 1000,
        height: 1400,
        coordinate_space: 'processed_image_pixels',
      },
      visual: {
        available: true,
        kind: 'processed_png',
        url: '/v1/doc/parse/test-review-req-123/pages/1/image',
      },
      reading_order: ['blk-p2-1'],
      blocks: [
        {
          block_id: 'blk-p2-1',
          type: 'text',
          content: 'Đại diện bên nhận ký tên xác nhận',
          confidence: 0.60, // < 0.75 => Page 2 Issue!
          confidence_source: 'real_engine',
          bbox: [
            { x: 100, y: 100 },
            { x: 350, y: 100 },
            { x: 350, y: 150 },
            { x: 100, y: 150 },
          ],
          bbox_normalized: [],
          page_index: 1,
          source_engine: 'paddleocr_vl',
          extra: {},
        },
      ],
      tables: [],
      confidence: 0.60,
    },
  ],
}

function uploadFile(container: HTMLElement, file: File) {
  const input = container.querySelector(
    'input[data-testid="global-file-input"]'
  ) as HTMLInputElement
  if (!input) {
    throw new Error('global-file-input not found!')
  }
  fireEvent.change(input, { target: { files: [file] } })
}

describe('Phase 2C — OCR Review Mode', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.HTMLElement.prototype.scrollIntoView = vi.fn()
  })

  // 1. search filters Vietnamese block content
  it('1. search filters Vietnamese block content case-insensitively', () => {
    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId={null}
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    // Type Vietnamese search term
    const searchInput = screen.getByLabelText(/search blocks/i)
    fireEvent.change(searchInput, { target: { value: 'Tuấn Thành' } })

    // Only blk-1 should be shown
    const visibleCards = screen.getAllByTestId('block-card')
    expect(visibleCards.length).toBe(1)
    expect(visibleCards[0]).toHaveTextContent('Tuấn Thành')

    // Test clear button
    const clearBtn = screen.getByLabelText(/clear search/i)
    fireEvent.click(clearBtn)
    expect(screen.getAllByTestId('block-card').length).toBe(5)
  })

  // 2. type filter works
  it('2. type filter filters blocks by chosen type', () => {
    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId={null}
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const typeSelect = screen.getByLabelText(/filter by type/i)
    fireEvent.change(typeSelect, { target: { value: 'title' } })

    const visibleCards = screen.getAllByTestId('block-card')
    expect(visibleCards.length).toBe(1)
    expect(visibleCards[0]).toHaveTextContent('PHIẾU XUẤT KHO KIÊM GIAO HÀNG')
  })

  // 3. low confidence filter only includes real_engine values below threshold
  it('3. low confidence filter only includes real_engine values below 0.75 threshold', () => {
    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId={null}
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const confSelect = screen.getByLabelText(/filter by confidence/i)
    fireEvent.change(confSelect, { target: { value: 'low' } })

    const visibleCards = screen.getAllByTestId('block-card')
    // blk-2 is real_engine with 0.65 (< 0.75). blk-3 has 0.50 but is synthesized so it is excluded.
    expect(visibleCards.length).toBe(1)
    expect(visibleCards[0]).toHaveTextContent('blk-2')
  })

  // 4. synthesized 0.50 is NOT classified as low OCR confidence
  it('4. synthesized 0.50 is NOT classified as low OCR confidence', () => {
    expect(OCR_REVIEW_LOW_CONFIDENCE_THRESHOLD).toBe(0.75)
    // Direct test of provenance rule
    expect(isReviewIssue(0.50, 'synthesized')).toBe(false)
    expect(isReviewIssue(0.10, 'synthesized')).toBe(false)
    expect(isReviewIssue(0.65, 'real_engine')).toBe(true)
    expect(isReviewIssue(0.95, 'real_engine')).toBe(false)
  })

  // 5. unknown confidence filter works
  it('5. unknown confidence filter works and shows unknown blocks', () => {
    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId={null}
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const confSelect = screen.getByLabelText(/filter by confidence/i)
    fireEvent.change(confSelect, { target: { value: 'unknown' } })

    const visibleCards = screen.getAllByTestId('block-card')
    expect(visibleCards.length).toBe(1)
    expect(visibleCards[0]).toHaveTextContent('blk-4')
  })

  // 6. page summary counts are correct
  it('6. page summary counts are correctly computed', () => {
    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId={null}
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    // Total: 5 blocks; low: 1 (blk-2); unknown: 1 (blk-4); derived: 1 (blk-3)
    expect(screen.getByText(/5 blocks/i)).toBeInTheDocument()
    expect(screen.getByText(/1 low confidence/i)).toBeInTheDocument()
    expect(screen.getByText(/1 unknown/i)).toBeInTheDocument()
    expect(screen.getByText(/1 derived/i)).toBeInTheDocument()
  })

  // 7. selected block detail shows correct metadata
  it('7. selected block detail section displays complete metadata', () => {
    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId="blk-2"
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const detailPanel = screen.getByTestId('block-detail-panel')
    expect(detailPanel).toBeInTheDocument()
    expect(detailPanel).toHaveTextContent('blk-2')
    expect(detailPanel).toHaveTextContent('TITLE')
    expect(detailPanel).toHaveTextContent('PHIẾU XUẤT KHO KIÊM GIAO HÀNG')
    expect(detailPanel).toHaveTextContent('65%')
    expect(detailPanel).toHaveTextContent('real_engine')
    expect(detailPanel).toHaveTextContent('paddleocr_vl')
    expect(detailPanel).toHaveTextContent('Available (4 pts)')
  })

  // 8. real confidence renders percent
  it('8. real confidence renders numeric percent', () => {
    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId="blk-1"
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const detailPanel = screen.getByTestId('block-detail-panel')
    expect(detailPanel).toHaveTextContent('95%')
  })

  // 9. synthesized renders Derived
  it('9. synthesized renders Derived in detail view without fake percent', () => {
    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId="blk-3"
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const detailPanel = screen.getByTestId('block-detail-panel')
    expect(detailPanel).toHaveTextContent('Derived')
    expect(detailPanel).not.toHaveTextContent('50%')
  })

  // 10. unknown renders Unavailable
  it('10. unknown renders Unavailable in detail view', () => {
    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId="blk-4"
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const detailPanel = screen.getByTestId('block-detail-panel')
    expect(detailPanel).toHaveTextContent('Unavailable')
  })

  // 11. copy block text works
  it('11. copy button writes block content to clipboard and shows Copied feedback', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    })

    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId="blk-1"
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const copyBtn = screen.getByRole('button', { name: /copy/i })
    fireEvent.click(copyBtn)

    expect(writeTextMock).toHaveBeenCalledWith('Công ty TNHH Tuấn Thành cung cấp vật tư')
    expect(screen.getByText('Copied')).toBeInTheDocument()
  })

  // 12. keyboard next/previous visible block works
  it('12. keyboard ArrowDown/ArrowUp and j/k keys navigate visible blocks', () => {
    const handleSelect = vi.fn()
    const page0 = mockReviewParseResponse.pages[0]

    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId="blk-1"
        hoveredBlockId={null}
        onBlockSelect={handleSelect}
        onBlockHover={vi.fn()}
      />
    )

    // Press ArrowDown -> should select next visible block (blk-2)
    fireEvent.keyDown(window, { key: 'ArrowDown' })
    expect(handleSelect).toHaveBeenCalledWith('blk-2')

    // Press k -> should select previous block (blk-5 or wrap)
    fireEvent.keyDown(window, { key: 'k' })
    expect(handleSelect).toHaveBeenCalledWith('blk-5')
  })

  // 13. next issue selects next low/unknown block
  it('13. next issue button navigates to next review issue', () => {
    const handleNavigate = vi.fn()
    const page0 = mockReviewParseResponse.pages[0]

    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId="blk-2" // First issue on page 0
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
        allPages={mockReviewParseResponse.pages}
        activePageIndex={0}
        onNavigateIssue={handleNavigate}
      />
    )

    const nextIssueBtn = screen.getByRole('button', { name: /next issue/i })
    fireEvent.click(nextIssueBtn)

    // Next issue is blk-4 (unknown) on page 0
    expect(handleNavigate).toHaveBeenCalledWith(0, 'blk-4')
  })

  // 14. next issue can move to another page
  it('14. next issue button moves across pages when issue is on Page 2', () => {
    const handleNavigate = vi.fn()
    const page0 = mockReviewParseResponse.pages[0]

    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId="blk-4" // Second issue (last on page 0)
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
        allPages={mockReviewParseResponse.pages}
        activePageIndex={0}
        onNavigateIssue={handleNavigate}
      />
    )

    const nextIssueBtn = screen.getByRole('button', { name: /next issue/i })
    fireEvent.click(nextIssueBtn)

    // Next issue is blk-p2-1 on page 1
    expect(handleNavigate).toHaveBeenCalledWith(1, 'blk-p2-1')
  })

  // 15. selected issue highlights bbox
  it('15. selected issue highlights bbox on SVG overlay with amber stroke', () => {
    const { container } = render(
      <OcrInspector
        pages={mockReviewParseResponse.pages}
        activePageIndex={0}
        selectedBlockId="blk-2" // Selected review issue
        hoveredBlockId={null}
        onPageChange={vi.fn()}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const img = screen.getByRole('img')
    fireEvent.load(img)

    const poly2 = container.querySelector('polygon[data-block-id="blk-2"]')
    expect(poly2).toHaveAttribute('stroke', '#f59e0b')

    // Unselected issue blk-4 should have amber dashed border
    const poly4 = container.querySelector('polygon[data-block-id="blk-4"]')
    expect(poly4).toHaveAttribute('stroke', '#d97706')
    expect(poly4).toHaveAttribute('stroke-dasharray', '4 2')
  })

  // 16. block without bbox can still be reviewed safely
  it('16. block without bbox can still be reviewed safely with geometry status', () => {
    const page0 = mockReviewParseResponse.pages[0]
    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId="blk-5" // Block with empty bbox
        hoveredBlockId={null}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const detailPanel = screen.getByTestId('block-detail-panel')
    expect(detailPanel).toHaveTextContent('No visual region available')
  })

  // 17. existing Phase 2B bbox interactions still pass
  it('17. existing Phase 2B bbox clicking and hovering functions correctly', () => {
    const handleSelect = vi.fn()
    const handleHover = vi.fn()

    const { container } = render(
      <OcrInspector
        pages={mockReviewParseResponse.pages}
        activePageIndex={0}
        selectedBlockId={null}
        hoveredBlockId={null}
        onPageChange={vi.fn()}
        onBlockSelect={handleSelect}
        onBlockHover={handleHover}
      />
    )

    const img = screen.getByRole('img')
    fireEvent.load(img)

    const poly1 = container.querySelector('polygon[data-block-id="blk-1"]')
    fireEvent.mouseEnter(poly1!)
    expect(handleHover).toHaveBeenCalledWith('blk-1')

    fireEvent.click(poly1!)
    expect(handleSelect).toHaveBeenCalledWith('blk-1')
  })

  // 18. Markdown/Preview regression unaffected
  it('18. Markdown/Preview regression unaffected in App', async () => {
    vi.mocked(apiClient.parseDocument).mockResolvedValueOnce(mockReviewParseResponse)

    const { container } = render(<App />)
    uploadFile(container, new File(['dummy'], 'invoice.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(screen.getAllByText('invoice.pdf').length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: /run ocr/i }))

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /preview/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('tab', { name: /preview/i }))
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /preview/i })).toHaveAttribute('aria-selected', 'true')
    })
  })

  // 19. Structured Extraction regression unaffected
  it('19. Structured Extraction regression unaffected', async () => {
    const mockExtraction = {
      request_id: 'test-extract-req',
      ocr: { decision: 'local', page_count: 1 },
      data: {
        po_number: 'PO-9922',
        po_date: '02-10-2026',
        items: [],
      },
      validation: {
        status: 'valid',
        attempts: 1,
        healed: false,
        issues: [],
      },
    }
    vi.mocked(apiClient.extractLocal).mockResolvedValueOnce(mockExtraction)

    const { container } = render(<App />)
    uploadFile(container, new File(['dummy'], 'invoice.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(screen.getAllByText('invoice.pdf').length).toBeGreaterThan(0))

    const extractionTab = screen.getByRole('tab', { name: /structured extraction/i })
    fireEvent.click(extractionTab)

    const runBtn = screen.getByRole('button', { name: /^extract$/i })
    fireEvent.click(runBtn)

    await waitFor(() => {
      expect(apiClient.extractLocal).toHaveBeenCalledTimes(1)
      expect(screen.getByRole('tab', { name: /fields/i })).toBeInTheDocument()
      expect(screen.getByText('PO-9922')).toBeInTheDocument()
    })
  })
})
