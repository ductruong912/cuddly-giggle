import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import App from './App'
import { getMessages } from './i18n'
import MarkdownResult from './MarkdownResult'
import { ocrFixture } from '../fixtures/ocrFixture'

const config = {
  supported_suffixes: ['.pdf', '.png', '.docx', '.tiff'],
  max_upload_bytes: 1024,
  pdf_max_pages: 3,
}
let ocr: Mock<(url: string, options: RequestInit) => Promise<Response>>
let fetchMock: Mock<(url: string, options: RequestInit) => Promise<Response>>

beforeEach(() => {
  ocr = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(ocrFixture('# Tài liệu\n\n| Cột | Giá trị |\n|---|---|\n|A|2|')), {
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  fetchMock = vi.fn((url: string, options: RequestInit) => {
    if (url === '/v1/ui/config') return Promise.resolve(new Response(JSON.stringify(config)))
    if (url === '/healthz') return Promise.resolve(new Response('{"status":"ok"}'))
    if (url === '/v1/doc/ocr/result?include_preview=true') return ocr(url, options)
    throw new Error(`Unexpected endpoint ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal(
    'URL',
    Object.assign(URL, {
      createObjectURL: vi.fn(() => 'blob:synthetic'),
      revokeObjectURL: vi.fn(),
    }),
  )
})

async function upload(name = 'synthetic.docx', content = 'synthetic') {
  const input = screen.getByLabelText('Chọn tài liệu', { selector: 'input' })
  await waitFor(() => expect(input).toBeEnabled())
  fireEvent.change(input, { target: { files: [new File([content], name)] } })
}

describe('OCR workspace', () => {
  it.each(['original', 'processed'])(
    'only shows bbox in Blocks without a checkbox: %s coordinates',
    async (coordinate_space) => {
      const t = getMessages('vi')
      const result = ocrFixture('# Synthetic OCR')
      const block = {
        block_id: 'region',
        page_index: 0,
        type: 'text',
        content: 'Synthetic region',
        bbox: [
          { x: 10, y: 20 },
          { x: 100, y: 20 },
          { x: 100, y: 50 },
        ],
        confidence: 0.95,
        source_engine: 'test',
        extra: {},
      }
      result.blocks = [block]
      result.pages = [
        {
          page_index: 0,
          blocks: [block],
          tables: [],
          reading_order: [block.block_id],
          confidence: 0.95,
          source_engine: 'test',
          geometry: { width: 200, height: 300, coordinate_space },
          preview_image: 'data:image/jpeg;base64,YQ==',
        },
      ]
      ocr.mockResolvedValue(
        new Response(JSON.stringify(result), {
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      const user = userEvent.setup()
      const { container } = render(<App />)
      await upload('synthetic.png')
      await user.click(screen.getByRole('button', { name: t.read }))
      const rendered = await screen.findByRole('tab', { name: t.rendered })
      expect(container.querySelector('.bbox-overlay')).toBeNull()
      expect(screen.queryByRole('checkbox', { name: t.bbox })).not.toBeInTheDocument()
      for (const name of ['Markdown', t.jsonOCR, t.rendered]) {
        await user.click(screen.getByRole('tab', { name: 'Blocks' }))
        expect(container.querySelector('.bbox-overlay')).not.toBeNull()
        await user.click(screen.getByRole('tab', { name }))
        expect(container.querySelector('.bbox-overlay')).toBeNull()
      }
      rendered.focus()
      await user.keyboard('{End}')
      expect(container.querySelector('.bbox-overlay')).not.toBeNull()
      await user.keyboard('{Home}')
      expect(container.querySelector('.bbox-overlay')).toBeNull()
    },
  )

  it('shows and exports OCR JSON, then shows recognized title and text regions', async () => {
    const result = ocrFixture('# OCR')
    result.blocks = [
      {
        block_id: 'title',
        page_index: 1,
        type: 'title',
        content: 'OCR title',
        bbox: [],
        confidence: 0.95,
        source_engine: 'test',
        extra: { label: 'paragraph_title' },
      },
      {
        block_id: 'text',
        page_index: 1,
        type: 'text',
        content: 'OCR text',
        bbox: [],
        confidence: 0.9,
        source_engine: 'test',
        extra: {},
      },
    ]
    ocr.mockResolvedValue(
      new Response(JSON.stringify(result), { headers: { 'Content-Type': 'application/json' } }),
    )
    const user = userEvent.setup()
    render(<App />)
    await upload()
    await user.click(screen.getByRole('button', { name: 'Đọc tài liệu' }))
    await user.click(await screen.findByRole('tab', { name: 'JSON OCR' }))
    expect(screen.getByRole('tabpanel')).toHaveTextContent('ocr_synthetic')
    await user.click(screen.getByRole('button', { name: 'Sao chép JSON OCR' }))
    expect(await navigator.clipboard.readText()).toBe(JSON.stringify(result, null, 2))
    await user.click(screen.getByRole('tab', { name: 'Blocks' }))
    expect(screen.queryByRole('tab', { name: 'Bảng' })).not.toBeInTheDocument()
    const title = screen.getByRole('button', { name: 'Nội dung 1 · title · Trang 2' })
    await user.hover(title)
    expect(title).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('heading', { name: 'OCR title' })).toBeVisible()
    expect(title).toHaveAttribute('data-block-type', 'title')
    expect(screen.getByText('PARAGRAPH_TITLE')).toBeVisible()
    expect(screen.getByText('TEXT')).toBeVisible()
    expect(screen.getByText('OCR text')).toBeVisible()
  })

  it('explains when no regions are available and navigates all four tabs', async () => {
    render(<App />)
    await upload()
    await userEvent.click(screen.getByRole('button', { name: 'Đọc tài liệu' }))
    const tab = await screen.findByRole('tab', { name: 'Trình bày' })
    tab.focus()
    await userEvent.keyboard('{End}')
    expect(screen.getByRole('tab', { name: 'Blocks' })).toHaveFocus()
    expect(screen.getByText(/Engine chưa trả block/)).toBeVisible()
    await userEvent.keyboard('{ArrowRight}')
    expect(tab).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'Blocks' })).toHaveFocus()
  })
  it('starts evenly split, supports keyboard resizing and resets for a new file', async () => {
    render(<App />)
    expect(screen.queryByRole('separator')).not.toBeInTheDocument()
    await upload()
    const divider = screen.getByRole('separator')
    expect(divider).toHaveAttribute('aria-valuenow', '50')
    divider.focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(divider).toHaveAttribute('aria-valuenow', '52')
    await userEvent.keyboard('{Shift>}{ArrowLeft}{/Shift}')
    expect(divider).toHaveAttribute('aria-valuenow', '42')
    await userEvent.keyboard('{Home}{ArrowLeft}')
    expect(divider).toHaveAttribute('aria-valuenow', '25')
    await userEvent.keyboard('{End}{ArrowRight}')
    expect(divider).toHaveAttribute('aria-valuenow', '75')
    await userEvent.keyboard('{Enter}')
    expect(divider).toHaveAttribute('aria-valuenow', '50')
    await userEvent.keyboard('{ArrowLeft}')
    await upload('second.docx')
    expect(divider).toHaveAttribute('aria-valuenow', '50')
    expect(ocr).not.toHaveBeenCalled()
  })

  it('handles selection, raw/rendered result, replacing a file and cleanup', async () => {
    const { unmount } = render(<App />)
    expect(screen.queryByRole('button', { name: 'Đọc tài liệu' })).not.toBeInTheDocument()
    await upload()
    expect(screen.getByText('Chưa hỗ trợ xem trước định dạng này.', { exact: false })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Đọc tài liệu' }))
    expect(await screen.findByRole('table')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Markdown' }))
    expect(screen.getByText(/# Tài liệu/)).toBeInTheDocument()
    await upload('second.tiff')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sao chép Markdown' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tài liệu mới' })).not.toBeInTheDocument()
    unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2)
    expect(
      fetchMock.mock.calls.every(
        ([path]) => !String(path).includes('extract') && path !== '/readyz',
      ),
    ).toBe(true)
  })

  it('blocks unsupported or oversized files before any OCR request', async () => {
    render(<App />)
    await upload('bad.exe')
    expect(screen.getByRole('alert')).toHaveTextContent('Định dạng')
    await upload('large.docx', 'x'.repeat(1025))
    expect(screen.getByRole('alert')).toHaveTextContent('giới hạn')
    expect(ocr).not.toHaveBeenCalled()
  })

  it('prevents duplicate submissions and file changes while processing', async () => {
    let finish!: (value: Response) => void
    ocr.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve
        }),
    )
    render(<App />)
    await upload()
    const button = screen.getByRole('button', { name: 'Đọc tài liệu' })
    fireEvent.click(button)
    fireEvent.click(button)
    expect(ocr).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Đổi file' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Mở thanh bên' })).toBeEnabled()
    expect(screen.getByText('Đã chờ 0 giây')).toBeInTheDocument()
    finish(
      new Response(JSON.stringify(ocrFixture('Done')), {
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    expect(await screen.findByText('Done')).toBeInTheDocument()
  })

  it('shows server errors and only retries on a new click', async () => {
    ocr.mockResolvedValueOnce(new Response('', { status: 503 }))
    render(<App />)
    await upload()
    await userEvent.click(screen.getByRole('button', { name: 'Đọc tài liệu' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('chưa sẵn sàng')
    expect(ocr).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(ocr).toHaveBeenCalledTimes(2)
  })

  it('handles lost connections without pretending the server cancelled work', async () => {
    ocr.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<App />)
    await upload()
    await userEvent.click(screen.getByRole('button', { name: 'Đọc tài liệu' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('vẫn đang được xử lý')
    expect(ocr).toHaveBeenCalledTimes(1)
  })

  it('supports arrow-key navigation of result tabs', async () => {
    render(<App />)
    await upload()
    await userEvent.click(screen.getByRole('button', { name: 'Đọc tài liệu' }))
    await screen.findByRole('table')
    const rendered = screen.getByRole('tab', { name: 'Trình bày' })
    rendered.focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Markdown' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Markdown' })).toHaveAttribute('aria-selected', 'true')
  })

  it('allows a fresh selection of the same file and revokes URLs on unmount', async () => {
    const { unmount } = render(<App />)
    await upload('first.docx')
    await upload('first.docx')
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1)
    unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2)
  })

  it('switches UI language without changing the selected file, OCR or split', async () => {
    render(<App />)
    await upload()
    await userEvent.click(screen.getByRole('button', { name: 'Đọc tài liệu' }))
    await screen.findByRole('table')
    const divider = screen.getByRole('separator')
    divider.focus()
    await userEvent.keyboard('{ArrowRight}')
    await userEvent.click(screen.getByRole('button', { name: 'Mở thanh bên' }))
    await userEvent.selectOptions(screen.getByLabelText('Ngôn ngữ'), 'en')
    expect(document.documentElement.lang).toBe('en')
    expect(screen.getByRole('region', { name: 'Settings' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Settings' })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Preview' })).toBeVisible()
    expect(screen.getByText('synthetic.docx')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Tài liệu' })).toBeVisible()
    expect(divider).toHaveAttribute('aria-valuenow', '52')
    expect(ocr).toHaveBeenCalledTimes(1)
    await userEvent.selectOptions(screen.getByLabelText('Language'), 'vi')
    expect(screen.getByRole('tab', { name: 'Trình bày' })).toBeVisible()
  })

  it('translates an existing error from sidebar settings and supports closing the sidebar', async () => {
    render(<App />)
    await upload('bad.exe')
    const toggle = screen.getByRole('button', { name: 'Mở thanh bên' })
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
    await userEvent.click(toggle)
    await userEvent.selectOptions(screen.getByLabelText('Ngôn ngữ'), 'en')
    expect(screen.getByRole('alert')).toHaveTextContent('Unsupported file format')
    const sidebar = screen.getByRole('complementary', { name: 'Sidebar' })
    expect(sidebar).toBeVisible()
    expect(sidebar.querySelector('#language-select')).not.toBeNull()
    expect(sidebar.querySelector('#preferences')).not.toHaveAttribute('popover')
    expect(sidebar.querySelector('nav')).toBeNull()
    await userEvent.keyboard('{Escape}')
    expect(toggle).toHaveFocus()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })
})

it('renders OCR HTML tables with merged cells alongside Markdown tables', () => {
  render(
    <MarkdownResult
      markdown={
        '# Kết quả\n\n<table><tr><th rowspan="2">Hạng mục</th><th colspan="2">Số lượng</th></tr><tr><th>Đặt</th><th>Giao</th></tr><tr><td>Tài liệu A</td><td>12</td><td>8</td></tr></table>\n\n| Ghi chú | Giá trị |\n|---|---|\n| Kiểm tra | Đủ |'
      }
    />,
  )
  expect(screen.getAllByRole('table')).toHaveLength(2)
  expect(screen.getByRole('columnheader', { name: 'Hạng mục' })).toHaveAttribute('rowspan', '2')
  expect(screen.getByRole('columnheader', { name: 'Số lượng' })).toHaveAttribute('colspan', '2')
  expect(screen.getByRole('cell', { name: 'Tài liệu A' })).toBeVisible()
  expect(screen.getByRole('cell', { name: '12' })).toBeVisible()
  expect(screen.getByRole('cell', { name: '8' })).toBeVisible()
})

it('renders untrusted Markdown without images, live links or executable HTML', () => {
  const { container } = render(
    <MarkdownResult
      markdown={
        '# Safe\n![tracking](https://example.com/tracker)\n[link](javascript:alert(1))\n<script>alert(1)</script>\n<img src="https://example.com/other" onerror="alert(1)" />\n<table style="background:url(https://example.com/style)" onclick="alert(1)"><tr><td><a href="javascript:alert(1)">Nội dung</a><iframe src="https://example.com/frame"></iframe><script>alert(1)</script></td></tr></table>'
      }
    />,
  )
  expect(container.querySelector('img, a, script, iframe')).toBeNull()
  expect(container.querySelector('[style], [onclick], [onerror]')).toBeNull()
  expect(screen.getByRole('cell', { name: 'Nội dung' })).toBeVisible()
  expect(screen.getByText('[Ảnh: tracking]')).toBeInTheDocument()
})
