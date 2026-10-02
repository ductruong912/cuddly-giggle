import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from '../App'
import { OcrInspector } from '../components/document/OcrInspector'
import { BlocksView } from '../components/extraction/BlocksView'
import { apiClient } from '../api/client'
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

const mockMultiPageParseResponse: DocumentParseResponse = {
  request_id: 'test-req-inspect-1',
  decision: { reason: 'local' },
  engine_name: 'PaddleOCR-VL',
  markdown: '# INVOICE DOCUMENT\nTotal: $500',
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
        url: '/v1/doc/parse/test-req-inspect-1/pages/0/image',
      },
      reading_order: ['block-2', 'block-1', 'block-3'],
      blocks: [
        {
          block_id: 'block-1',
          type: 'text',
          content: 'First content line for block 1',
          confidence: 0.962,
          confidence_source: 'real_engine',
          bbox: [
            { x: 100, y: 100 },
            { x: 300, y: 100 },
            { x: 300, y: 150 },
            { x: 100, y: 150 },
          ],
          bbox_normalized: [],
          page_index: 0,
          source_engine: 'PaddleOCR-VL',
          extra: {},
        },
        {
          block_id: 'block-2',
          type: 'title',
          content: 'Header Title Block 2',
          confidence: 0.98,
          confidence_source: 'synthesized',
          bbox: [
            { x: 50, y: 20 },
            { x: 400, y: 20 },
            { x: 400, y: 80 },
            { x: 50, y: 80 },
          ],
          bbox_normalized: [],
          page_index: 0,
          source_engine: 'PaddleOCR-VL',
          extra: {},
        },
        {
          block_id: 'block-3',
          type: 'table',
          content: 'Table without bbox block 3',
          confidence: 0.5,
          confidence_source: 'unknown',
          bbox: [], // No bbox points
          bbox_normalized: [],
          page_index: 0,
          source_engine: 'PaddleOCR-VL',
          extra: {},
        },
      ],
      tables: [],
      confidence: 0.95,
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
        url: '/v1/doc/parse/test-req-inspect-1/pages/1/image',
      },
      reading_order: ['block-p2-1'],
      blocks: [
        {
          block_id: 'block-p2-1',
          type: 'text',
          content: 'Page 2 unique content block',
          confidence: 0.88,
          confidence_source: 'real_engine',
          bbox: [
            { x: 60, y: 60 },
            { x: 250, y: 60 },
            { x: 250, y: 120 },
            { x: 60, y: 120 },
          ],
          bbox_normalized: [],
          page_index: 1,
          source_engine: 'PaddleOCR-VL',
          extra: {},
        },
      ],
      tables: [],
      confidence: 0.88,
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

describe('Phase 2B — OCR Visual Inspector Frontend', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.HTMLElement.prototype.scrollIntoView = vi.fn()
  })

  // 1. parseDocument calls POST /v1/doc/parse only once
  it('1. parseDocument calls POST /v1/doc/parse only once upon clicking Run OCR', async () => {
    vi.mocked(apiClient.parseDocument).mockResolvedValueOnce(mockMultiPageParseResponse)

    const { container } = render(<App />)
    const file = new File(['dummy content'], 'invoice.pdf', { type: 'application/pdf' })
    uploadFile(container, file)

    await waitFor(() => expect(screen.getAllByText('invoice.pdf').length).toBeGreaterThan(0))

    const runBtn = screen.getByRole('button', { name: /run ocr/i })
    fireEvent.click(runBtn)

    await waitFor(() => {
      expect(apiClient.parseDocument).toHaveBeenCalledTimes(1)
      expect(apiClient.ocrDocument).not.toHaveBeenCalled()
    })
  })

  // 2. OCR result renders markdown from DocumentParseResponse
  it('2. renders markdown from DocumentParseResponse in Markdown tab', async () => {
    vi.mocked(apiClient.parseDocument).mockResolvedValueOnce(mockMultiPageParseResponse)

    const { container } = render(<App />)
    uploadFile(container, new File(['content'], 'invoice.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(screen.getAllByText('invoice.pdf').length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: /run ocr/i }))

    await waitFor(() => {
      expect(screen.getByText(/INVOICE DOCUMENT/i)).toBeInTheDocument()
      expect(screen.getByText(/Total: \$500/i)).toBeInTheDocument()
    })
  })

  // 3. OCR Inspector toggle appears when visual.available=true
  it('3. OCR Inspector toggle appears in Source panel when visual.available=true', async () => {
    vi.mocked(apiClient.parseDocument).mockResolvedValueOnce(mockMultiPageParseResponse)

    const { container } = render(<App />)
    uploadFile(container, new File(['content'], 'invoice.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(screen.getAllByText('invoice.pdf').length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: /run ocr/i }))

    await waitFor(() => {
      const originalTab = screen.getByRole('tab', { name: /original/i })
      const inspectorTab = screen.getByRole('tab', { name: /ocr inspector/i })
      expect(originalTab).toBeInTheDocument()
      expect(inspectorTab).toBeInTheDocument()
      // Default view mode must be Original
      expect(originalTab).toHaveAttribute('aria-selected', 'true')
      expect(inspectorTab).toHaveAttribute('aria-selected', 'false')
    })
  })

  // 4. toggle does not appear when no visual available
  it('4. toggle does not appear when no visual is available', async () => {
    const noVisualResponse: DocumentParseResponse = {
      ...mockMultiPageParseResponse,
      pages: [
        {
          ...mockMultiPageParseResponse.pages[0],
          visual: { available: false, kind: null, url: null },
        },
      ],
    }
    vi.mocked(apiClient.parseDocument).mockResolvedValueOnce(noVisualResponse)

    const { container } = render(<App />)
    uploadFile(container, new File(['content'], 'document.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))

    await waitFor(() => expect(screen.getAllByText('document.docx').length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: /run ocr/i }))

    await waitFor(() => {
      expect(screen.queryByRole('tab', { name: /ocr inspector/i })).not.toBeInTheDocument()
    })
  })

  // 5. correct processed image URL used
  it('5. correct processed image URL is used by OcrInspector', () => {
    render(
      <OcrInspector
        pages={mockMultiPageParseResponse.pages}
        activePageIndex={0}
        selectedBlockId={null}
        hoveredBlockId={null}
        onPageChange={vi.fn()}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const img = screen.getByRole('img')
    expect(img).toHaveAttribute(
      'src',
      '/v1/doc/parse/test-req-inspect-1/pages/0/image'
    )
  })

  // 6. SVG polygon renders using real bbox
  it('6. SVG polygon renders using real bbox coordinates and correct points', () => {
    const { container } = render(
      <OcrInspector
        pages={mockMultiPageParseResponse.pages}
        activePageIndex={0}
        selectedBlockId={null}
        hoveredBlockId={null}
        onPageChange={vi.fn()}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    // Trigger image load to render SVG
    const img = screen.getByRole('img')
    fireEvent.load(img)

    const polygon1 = container.querySelector('polygon[data-block-id="block-1"]')
    expect(polygon1).toBeInTheDocument()
    expect(polygon1).toHaveAttribute(
      'points',
      '100,100 300,100 300,150 100,150'
    )
  })

  // 7. block without bbox does not create fake polygon
  it('7. block without bbox does not create fake polygon overlay', () => {
    const { container } = render(
      <OcrInspector
        pages={mockMultiPageParseResponse.pages}
        activePageIndex={0}
        selectedBlockId={null}
        hoveredBlockId={null}
        onPageChange={vi.fn()}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const img = screen.getByRole('img')
    fireEvent.load(img)

    // block-3 has empty bbox
    const polygon3 = container.querySelector('polygon[data-block-id="block-3"]')
    expect(polygon3).not.toBeInTheDocument()
  })

  // 8. Blocks tab filters blocks by active page
  it('8. Blocks tab filters blocks by active page', async () => {
    vi.mocked(apiClient.parseDocument).mockResolvedValueOnce(mockMultiPageParseResponse)

    const { container } = render(<App />)
    uploadFile(container, new File(['content'], 'invoice.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(screen.getAllByText('invoice.pdf').length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: /run ocr/i }))

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /blocks/i })).toBeInTheDocument()
    })

    // Click Blocks tab
    fireEvent.click(screen.getByRole('tab', { name: /blocks/i }))

    // Active page is 0, so block-1 and block-2 are visible, but not block-p2-1
    await waitFor(() => {
      expect(screen.getByText(/First content line for block 1/i)).toBeInTheDocument()
      expect(screen.getByText(/Header Title Block 2/i)).toBeInTheDocument()
      expect(screen.queryByText(/Page 2 unique content block/i)).not.toBeInTheDocument()
    })
  })

  // 9. reading_order respected
  it('9. Blocks tab respects reading_order sequence', () => {
    const page0 = mockMultiPageParseResponse.pages[0]
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

    const buttons = screen.getAllByTestId('block-card')
    // reading_order is ['block-2', 'block-1', 'block-3']
    expect(buttons[0]).toHaveTextContent('Header Title Block 2')
    expect(buttons[1]).toHaveTextContent('First content line for block 1')
    expect(buttons[2]).toHaveTextContent('Table without bbox block 3')
  })

  // 10. hover block highlights corresponding bbox
  it('10. hover block highlights corresponding bbox with hovered style', () => {
    const { container } = render(
      <OcrInspector
        pages={mockMultiPageParseResponse.pages}
        activePageIndex={0}
        selectedBlockId={null}
        hoveredBlockId="block-1"
        onPageChange={vi.fn()}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const img = screen.getByRole('img')
    fireEvent.load(img)

    const polygon1 = container.querySelector('polygon[data-block-id="block-1"]')
    expect(polygon1).toHaveAttribute('stroke', '#3b82f6')
  })

  // 11. click block selects bbox
  it('11. clicking block invokes onBlockSelect with blockId', () => {
    const handleSelect = vi.fn()
    const page0 = mockMultiPageParseResponse.pages[0]

    render(
      <BlocksView
        blocks={page0.blocks}
        readingOrder={page0.reading_order}
        selectedBlockId={null}
        hoveredBlockId={null}
        onBlockSelect={handleSelect}
        onBlockHover={vi.fn()}
      />
    )

    const card = screen.getByText(/Header Title Block 2/i)
    fireEvent.click(card)
    expect(handleSelect).toHaveBeenCalledWith('block-2')
  })

  // 12. click bbox selects/scrolls block
  it('12. click bbox selects block via onBlockSelect', () => {
    const handleSelect = vi.fn()
    const { container } = render(
      <OcrInspector
        pages={mockMultiPageParseResponse.pages}
        activePageIndex={0}
        selectedBlockId={null}
        hoveredBlockId={null}
        onPageChange={vi.fn()}
        onBlockSelect={handleSelect}
        onBlockHover={vi.fn()}
      />
    )

    const img = screen.getByRole('img')
    fireEvent.load(img)

    const polygon1 = container.querySelector('polygon[data-block-id="block-1"]')
    expect(polygon1).toBeInTheDocument()
    fireEvent.click(polygon1!)
    expect(handleSelect).toHaveBeenCalledWith('block-1')
  })

  // 13. page navigation updates Blocks list
  it('13. page navigation updates active page and filters blocks accordingly', async () => {
    vi.mocked(apiClient.parseDocument).mockResolvedValueOnce(mockMultiPageParseResponse)

    const { container } = render(<App />)
    uploadFile(container, new File(['content'], 'invoice.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(screen.getAllByText('invoice.pdf').length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: /run ocr/i }))

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /ocr inspector/i })).toBeInTheDocument()
    })

    // Switch to OCR Inspector
    fireEvent.click(screen.getByRole('tab', { name: /ocr inspector/i }))

    // Switch to Blocks tab
    fireEvent.click(screen.getByRole('tab', { name: /blocks/i }))

    await waitFor(() => {
      expect(screen.getByText(/First content line for block 1/i)).toBeInTheDocument()
    })

    // Wait for OcrInspector lazy-load and click Next Page
    const nextBtn = await screen.findByRole('button', { name: /next page/i })
    fireEvent.click(nextBtn)

    // Now Blocks list shows Page 2 content
    await waitFor(() => {
      expect(screen.getByText(/Page 2 unique content block/i)).toBeInTheDocument()
      expect(screen.queryByText(/First content line for block 1/i)).not.toBeInTheDocument()
    })
  })

  // 14. real_engine confidence displays numeric percent
  it('14. real_engine confidence displays numeric percent badge', () => {
    const page0 = mockMultiPageParseResponse.pages[0]
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

    // block-1 has confidence 0.962 and source 'real_engine' -> 96%
    expect(screen.getByText('96%')).toBeInTheDocument()
  })

  // 15. synthesized confidence displays Derived, not a percent
  it('15. synthesized confidence displays Derived, not a percent', () => {
    const page0 = mockMultiPageParseResponse.pages[0]
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

    // block-2 has confidence 0.98 and source 'synthesized' -> Derived
    expect(screen.getByText('Derived')).toBeInTheDocument()
    expect(screen.queryByText('98%')).not.toBeInTheDocument()
  })

  // 16. unknown confidence does not display fake percent
  it('16. unknown confidence does not display fake percent', () => {
    const page0 = mockMultiPageParseResponse.pages[0]
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

    // block-3 has confidence 0.5 but source 'unknown' -> NO 50%
    expect(screen.queryByText('50%')).not.toBeInTheDocument()
  })

  // 17. visual image 404/error shows graceful recovery UI
  it('17. visual image 404 or load error shows graceful recovery message', () => {
    render(
      <OcrInspector
        pages={mockMultiPageParseResponse.pages}
        activePageIndex={0}
        selectedBlockId={null}
        hoveredBlockId={null}
        onPageChange={vi.fn()}
        onBlockSelect={vi.fn()}
        onBlockHover={vi.fn()}
      />
    )

    const img = screen.getByRole('img')
    // Trigger image load error (such as 404 artifact expired)
    fireEvent.error(img)

    expect(
      screen.getByText(/OCR visualization is no longer available/i)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Re-run OCR to regenerate the page visualization/i)
    ).toBeInTheDocument()
  })

  // 18. existing Markdown/Preview functionality still works
  it('18. existing Markdown/Preview tabs continue to function normally', async () => {
    vi.mocked(apiClient.parseDocument).mockResolvedValueOnce(mockMultiPageParseResponse)

    const { container } = render(<App />)
    uploadFile(container, new File(['content'], 'invoice.pdf', { type: 'application/pdf' }))

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

  // 19. Structured Extraction Fields/JSON/Validation unaffected
  it('19. Structured Extraction Fields/JSON/Validation tabs remain unaffected', async () => {
    const mockExtraction = {
      request_id: 'test-extract-req',
      ocr: { decision: 'local', page_count: 1 },
      data: {
        po_number: 'PO-7788',
        po_date: '02-10-2026',
        items: [
          {
            toto_number: 'TOTO-01',
            customer_number: 'CUST-01',
            quantity: 5,
            unit_price: 100,
            extension: 500,
          },
        ],
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
    uploadFile(container, new File(['content'], 'invoice.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(screen.getAllByText('invoice.pdf').length).toBeGreaterThan(0))

    // Switch mode to Structured Extraction
    const extractionTab = screen.getByRole('tab', { name: /structured extraction/i })
    fireEvent.click(extractionTab)

    const runBtn = screen.getByRole('button', { name: /^extract$/i })
    fireEvent.click(runBtn)

    await waitFor(() => {
      expect(apiClient.extractLocal).toHaveBeenCalledTimes(1)
      expect(screen.getByRole('tab', { name: /fields/i })).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: /json/i })).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: /validation/i })).toBeInTheDocument()
      expect(screen.getByText('PO-7788')).toBeInTheDocument()
    })
  })
})
