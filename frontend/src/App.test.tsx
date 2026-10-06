import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import App from './App'
import MarkdownResult from './MarkdownResult'

const config = {
  supported_suffixes: ['.pdf', '.png', '.docx', '.tiff'],
  max_upload_bytes: 1024,
  pdf_max_pages: 3,
}
let ocr: Mock<(url: string, options: RequestInit) => Promise<Response>>
let fetchMock: Mock<(url: string, options: RequestInit) => Promise<Response>>

beforeEach(() => {
  ocr = vi.fn().mockResolvedValue(
    new Response('# Tài liệu\n\n| Cột | Giá trị |\n|---|---|\n|A|2|', {
      headers: { 'Content-Type': 'text/markdown' },
    }),
  )
  fetchMock = vi.fn((url: string, options: RequestInit) => {
    if (url === '/v1/ui/config') return Promise.resolve(new Response(JSON.stringify(config)))
    if (url === '/healthz') return Promise.resolve(new Response('{"status":"ok"}'))
    if (url === '/v1/doc/ocr') return ocr(url, options)
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

  it('handles selection, raw/rendered result, replacing a file and reset', async () => {
    render(<App />)
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
    await userEvent.click(screen.getByRole('button', { name: 'Tài liệu mới' }))
    expect(screen.queryByRole('button', { name: 'Đọc tài liệu' })).not.toBeInTheDocument()
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
    expect(screen.getByRole('button', { name: 'Tài liệu mới' })).toBeDisabled()
    expect(screen.getByText('Đã chờ 0 giây')).toBeInTheDocument()
    finish(new Response('Done', { headers: { 'Content-Type': 'text/markdown' } }))
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
