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
  ocr = vi
    .fn()
    .mockResolvedValue(
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
  it('handles selection, raw/rendered result, replacing a file and reset', async () => {
    render(<App />)
    expect(screen.getByRole('button', { name: 'Chạy OCR' })).toBeDisabled()
    await upload()
    expect(screen.getByText('Chưa hỗ trợ xem trước định dạng này.', { exact: false })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Chạy OCR' }))
    expect(await screen.findByRole('table')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Markdown' }))
    expect(screen.getByText(/# Tài liệu/)).toBeInTheDocument()
    await upload('second.tiff')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sao chép Markdown' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Tài liệu mới' }))
    expect(screen.getByRole('button', { name: 'Chạy OCR' })).toBeDisabled()
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
    const button = screen.getByRole('button', { name: 'Chạy OCR' })
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
    await userEvent.click(screen.getByRole('button', { name: 'Chạy OCR' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('chưa sẵn sàng')
    expect(ocr).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại OCR' }))
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(ocr).toHaveBeenCalledTimes(2)
  })

  it('handles lost connections without pretending the server cancelled work', async () => {
    ocr.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<App />)
    await upload()
    await userEvent.click(screen.getByRole('button', { name: 'Chạy OCR' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('vẫn đang được xử lý')
    expect(ocr).toHaveBeenCalledTimes(1)
  })

  it('supports arrow-key navigation of result tabs', async () => {
    render(<App />)
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

it('renders untrusted Markdown without images, live links or executable HTML', () => {
  const { container } = render(
    <MarkdownResult
      markdown={
        '# Safe\n![tracking](https://example.com/tracker)\n[link](javascript:alert(1))\n<script>alert(1)</script>\n<img src="https://example.com/other" />'
      }
    />,
  )
  expect(container.querySelector('img, a, script, iframe')).toBeNull()
  expect(screen.getByText('[Ảnh: tracking]')).toBeInTheDocument()
})
