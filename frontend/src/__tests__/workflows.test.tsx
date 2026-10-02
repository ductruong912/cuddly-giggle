import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from '../App'
import { PoFieldsTab } from '../components/extraction/PoFieldsTab'
import { ValidationTab } from '../components/extraction/ValidationTab'
import { MarkdownTab } from '../components/extraction/MarkdownTab'
import { HistoryDrawer } from '../components/history/HistoryDrawer'
import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import type { LLMExtractionResponse, ExtractionListResponse } from '../types/api'

// Mock global fetch or apiClient
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
    ocrDocument: vi.fn(),
    parseDocument: vi.fn().mockResolvedValue({
      request_id: 'test-req-1',
      decision: { reason: 'local' },
      engine_name: 'PaddleOCR-VL',
      markdown: '# DEFAULT MARKDOWN',
      pages: [],
    }),
    extractLocal: vi.fn(),
    getExtractions: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 }),
    getExtraction: vi.fn(),
  },
}))

function uploadFile(container: HTMLElement, file: File) {
  const input = container.querySelector(
    'input[data-testid="global-file-input"]'
  ) as HTMLInputElement
  if (!input) {
    throw new Error('global-file-input not found!')
  }
  fireEvent.change(input, { target: { files: [file] } })
}

describe('Frontend Workflows and Error Hardening', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default mock responses for health endpoints
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/readyz')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: 'ready',
              checks: {
                vl_runtime: 'ok',
                llm_credentials: 'ok',
                stages: 'ok',
                database: 'ok',
              },
              stages: {},
            }),
        })
      }
      if (url.includes('/healthz')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'ok' }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })
  })

  // 1. Valid PDF upload
  it('1. handles valid PDF upload correctly', async () => {
    const { container } = render(<App />)
    const file = new File(['%PDF-1.4 dummy content'], 'invoice.pdf', {
      type: 'application/pdf',
    })

    uploadFile(container, file)

    await waitFor(() => {
      expect(screen.getAllByText('invoice.pdf').length).toBeGreaterThan(0)
      expect(screen.getByText(/source/i)).toBeInTheDocument()
    })
  })

  // 2. Invalid extension
  it('2. rejects file with invalid extension and shows error', async () => {
    const { container } = render(<App />)
    const file = new File(['binary content'], 'script.exe', {
      type: 'application/x-msdownload',
    })

    uploadFile(container, file)

    await waitFor(() => {
      expect(screen.getByText(/unsupported file type/i)).toBeInTheDocument()
    })
  })

  // 3. File > 50 MB
  it('3. rejects file larger than 50 MB', async () => {
    const { container } = render(<App />)
    const bigFile = new File(['dummy'], 'large_document.pdf', {
      type: 'application/pdf',
    })
    Object.defineProperty(bigFile, 'size', { value: 55 * 1024 * 1024 }) // 55MB

    uploadFile(container, bigFile)

    await waitFor(() => {
      expect(screen.getByText(/file is too large/i)).toBeInTheDocument()
    })
  })

  // 4. OCR success
  it('4. displays markdown result on OCR success', async () => {
    vi.mocked(apiClient.parseDocument).mockResolvedValueOnce({
      request_id: 'test-req-4',
      decision: { reason: 'local' },
      engine_name: 'PaddleOCR-VL',
      markdown: '# PURCHASE ORDER\nPO Number: PO-9988\nAmount: $1,250.00',
      pages: [],
    })

    const { container } = render(<App />)
    const file = new File(['dummy pdf'], 'order.pdf', { type: 'application/pdf' })
    uploadFile(container, file)

    await waitFor(() => expect(screen.getAllByText('order.pdf').length).toBeGreaterThan(0))

    const runBtn = screen.getByRole('button', { name: /run ocr/i })
    fireEvent.click(runBtn)

    await waitFor(() => {
      expect(screen.getByText(/characters/i)).toBeInTheDocument()
      expect(screen.getByText(/PURCHASE ORDER/i)).toBeInTheDocument()
    })
  })

  // 4b. OCR result with HTML table switches between raw Markdown tab and rendered Preview tab
  it('4b. switches seamlessly between raw Markdown tab and rendered Preview tab with HTML table', async () => {
    const ocrWithTable = `# PHIẾU XUẤT KHO\n\n<table border=1><tr><th>Mã SP</th><th>SL</th></tr><tr><td>SP-01</td><td>50</td></tr></table>`
    vi.mocked(apiClient.parseDocument).mockResolvedValueOnce({
      request_id: 'test-req-4b',
      decision: { reason: 'local' },
      engine_name: 'PaddleOCR-VL',
      markdown: ocrWithTable,
      pages: [],
    })

    const { container } = render(<App />)
    const file = new File(['dummy pdf'], 'order.pdf', { type: 'application/pdf' })
    uploadFile(container, file)

    await waitFor(() => expect(screen.getAllByText('order.pdf').length).toBeGreaterThan(0))

    const runBtn = screen.getByRole('button', { name: /run ocr/i })
    fireEvent.click(runBtn)

    // Initially in Markdown tab: displays raw <table border=1> text
    await waitFor(() => {
      expect(screen.getByText(/<table border=1>/i)).toBeInTheDocument()
    })

    // Switch to Preview tab
    const previewTab = screen.getByRole('tab', { name: /preview/i })
    fireEvent.click(previewTab)

    // Now Preview renders real HTML table element, and literal tags are gone
    await waitFor(() => {
      const tableEl = container.querySelector('table')
      expect(tableEl).toBeInTheDocument()
      expect(screen.getByText('Mã SP')).toBeInTheDocument()
      expect(screen.getByText('SP-01')).toBeInTheDocument()
      expect(screen.queryByText(/<table border=1>/i)).not.toBeInTheDocument()
    })

    // Switch back to Markdown tab
    const markdownTab = screen.getByRole('tab', { name: /markdown/i })
    fireEvent.click(markdownTab)

    // Raw markdown source is visible again
    await waitFor(() => {
      expect(screen.getByText(/<table border=1>/i)).toBeInTheDocument()
    })
  })

  // 5. OCR error response
  it('5. displays error UI with Try again button on OCR error response', async () => {
    vi.mocked(apiClient.parseDocument).mockRejectedValueOnce(
      new ApiError(504, 'OCR process timed out', 'Server took too long to parse document')
    )

    const { container } = render(<App />)
    const file = new File(['dummy pdf'], 'order.pdf', { type: 'application/pdf' })
    uploadFile(container, file)

    await waitFor(() => expect(screen.getAllByText('order.pdf').length).toBeGreaterThan(0))

    const runBtn = screen.getByRole('button', { name: /run ocr/i })
    fireEvent.click(runBtn)

    await waitFor(() => {
      expect(screen.getByText(/OCR timed out/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
    })
  })

  // 6. Request cancellation
  it('6. safely handles request cancellation without crashing', async () => {
    vi.mocked(apiClient.parseDocument).mockImplementation(
      () =>
        new Promise((_, reject) => {
          setTimeout(() => {
            const err = new Error('The user aborted a request.')
            err.name = 'AbortError'
            reject(new ApiError(0, 'Request aborted by user.', undefined, true))
          }, 100)
        })
    )

    const { container } = render(<App />)
    const file = new File(['dummy pdf'], 'order.pdf', { type: 'application/pdf' })
    uploadFile(container, file)

    await waitFor(() => expect(screen.getAllByText('order.pdf').length).toBeGreaterThan(0))

    const runBtn = screen.getByRole('button', { name: /run ocr/i })
    fireEvent.click(runBtn)

    // Cancel while running
    await waitFor(() => {
      const cancelBtn = screen.getByRole('button', { name: /cancel processing/i })
      fireEvent.click(cancelBtn)
    })

    // Should return to idle without error banner
    await waitFor(() => {
      expect(screen.queryByText(/Processing Request Failed/i)).not.toBeInTheDocument()
    })
  })

  // 7. Structured extraction valid
  it('7. renders valid structured extraction with fields and line items', () => {
    const mockResponse: LLMExtractionResponse = {
      request_id: 'req-123',
      ocr: { decision: 'local', page_count: 2 },
      data: {
        po_number: 'PO-2026-001',
        po_date: '02-10-2026',
        items: [
          {
            toto_number: 'THX-990',
            customer_number: 'CUST-11',
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

    render(<PoFieldsTab response={mockResponse} />)

    expect(screen.getByText('PO-2026-001')).toBeInTheDocument()
    expect(screen.getByText('02-10-2026')).toBeInTheDocument()
    expect(screen.getByText('2 pages')).toBeInTheDocument()
    expect(screen.getByText('valid')).toBeInTheDocument()
    expect(screen.getByText('THX-990')).toBeInTheDocument()
    expect(screen.getAllByText('500.00').length).toBe(2)
  })

  // 8. Structured extraction needs_review
  it('8. renders subtle warning styling and issues for needs_review validation', () => {
    const mockValidation = {
      status: 'needs_review' as const,
      attempts: 2,
      healed: true,
      issues: [
        {
          field: 'items[0].extension',
          message: 'Computed extension does not match item sum',
          severity: 'warning' as const,
        },
      ],
    }

    render(<ValidationTab validation={mockValidation} />)

    expect(screen.getByText('Review Recommended')).toBeInTheDocument()
    expect(screen.getByText('needs_review')).toBeInTheDocument()
    expect(screen.getByText('items[0].extension')).toBeInTheDocument()
    expect(
      screen.getByText('Computed extension does not match item sum')
    ).toBeInTheDocument()
    expect(screen.getByText('warning')).toBeInTheDocument()
  })

  // 9. Safe rendering when items missing or null (No NaN / crash)
  it('9. renders safely without NaN or crash when items or fields are null/undefined', () => {
    const malformedResponse: any = {
      request_id: 'req-bad',
      ocr: null,
      data: {
        po_number: null,
        po_date: null,
        items: [
          {
            toto_number: null,
            customer_number: null,
            quantity: null,
            unit_price: null,
            extension: null,
          },
          null, // Null item in array
        ],
      },
      validation: null,
    }

    render(<PoFieldsTab response={malformedResponse} />)

    // Ensure Not found placeholders are shown safely and computed total is 0.00, not NaN
    expect(screen.getAllByText('Not found').length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
    expect(screen.getByText('0.00')).toBeInTheDocument()
  })

  // 10. History unavailable
  it('10. renders graceful unavailable state when history persistence is disabled', async () => {
    vi.mocked(apiClient.getExtractions).mockRejectedValueOnce(
      new Error('Extraction history is unavailable')
    )

    render(
      <HistoryDrawer
        isOpen={true}
        onClose={vi.fn()}
        onSelectExtraction={vi.fn()}
      />
    )

    await waitFor(() => {
      expect(
        screen.getByText(/Extraction history is unavailable/i)
      ).toBeInTheDocument()
    })
  })

  // 11. History available with search & status filters
  it('11. renders past extractions and filters by filename and status', async () => {
    const mockList: ExtractionListResponse = {
      items: [
        {
          id: 1,
          request_id: 'rec-1',
          source_filename: 'order_one.pdf',
          route: '/v1/extract/local',
          engine: null,
          page_count: 1,
          po_number: '12345',
          po_date: '01-10-2026',
          validation_status: 'valid',
          attempts: 1,
          healed: false,
          data: {},
          issues: [],
          duration_ms: 1200,
          created_at: '2026-10-01T12:00:00Z',
        },
        {
          id: 2,
          request_id: 'rec-2',
          source_filename: 'scan_two.pdf',
          route: '/v1/extract/local',
          engine: null,
          page_count: 3,
          po_number: '67890',
          po_date: '02-10-2026',
          validation_status: 'needs_review',
          attempts: 2,
          healed: true,
          data: {},
          issues: [],
          duration_ms: 3500,
          created_at: '2026-10-02T08:00:00Z',
        },
      ],
      total: 2,
      limit: 50,
      offset: 0,
    }

    vi.mocked(apiClient.getExtractions).mockResolvedValueOnce(mockList)

    render(
      <HistoryDrawer
        isOpen={true}
        onClose={vi.fn()}
        onSelectExtraction={vi.fn()}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('order_one.pdf')).toBeInTheDocument()
      expect(screen.getByText('scan_two.pdf')).toBeInTheDocument()
    })

    // Filter by Valid status
    const validBtn = screen.getByRole('button', { name: /^valid$/i })
    fireEvent.click(validBtn)

    expect(screen.getByText('order_one.pdf')).toBeInTheDocument()
    expect(screen.queryByText('scan_two.pdf')).not.toBeInTheDocument()

    // Filter by search query
    const searchInput = screen.getByPlaceholderText(/search filename or po number/i)
    fireEvent.change(searchInput, { target: { value: '99999' } })

    expect(screen.getByText(/no extractions match your search/i)).toBeInTheDocument()
  })

  // 12. Output search
  it('12. finds and highlights Unicode Vietnamese search matches in markdown output', () => {
    const markdown =
      'Biên bản nghiệm thu công trình.\nĐơn hàng số PO-8821.\nNghiệm thu đợt 1 hoàn tất.'

    render(<MarkdownTab markdown={markdown} filename="test.md" />)

    // Open search bar
    const findBtn = screen.getByRole('button', { name: /search in output/i })
    fireEvent.click(findBtn)

    const searchInput = screen.getByPlaceholderText(/find in document/i)
    fireEvent.change(searchInput, { target: { value: 'nghiệm thu' } })

    // Match count should be 2 matches (case-insensitive Vietnamese Unicode)
    expect(screen.getByText('1 / 2')).toBeInTheDocument()

    // Next match navigation
    const nextBtn = screen.getByRole('button', { name: /next match/i })
    fireEvent.click(nextBtn)
    expect(screen.getByText('2 / 2')).toBeInTheDocument()
  })
})
