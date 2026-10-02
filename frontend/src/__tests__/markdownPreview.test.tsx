import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { MarkdownPreview } from '../components/extraction/MarkdownPreview'
import { MarkdownTab } from '../components/extraction/MarkdownTab'
import * as utils from '../lib/utils'

describe('MarkdownPreview - Safe Raw HTML and Table Rendering', () => {
  // A. Raw HTML table
  it('A. renders raw HTML table into real table element and does not show literal table tags', () => {
    const rawHtmlMarkdown = `# Phiếu xuất kho

<table>
<tr>
<th>Mã hàng</th>
<th>Số lượng</th>
</tr>
<tr>
<td>ABC123</td>
<td>24</td>
</tr>
</table>`

    const { container } = render(<MarkdownPreview markdown={rawHtmlMarkdown} />)

    // Heading should be rendered
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Phiếu xuất kho')

    // Must contain a real <table> element
    const tableEl = container.querySelector('table')
    expect(tableEl).toBeInTheDocument()

    // Table headers and cells
    expect(screen.getByText('Mã hàng')).toBeInTheDocument()
    expect(screen.getByText('Số lượng')).toBeInTheDocument()
    expect(screen.getByText('ABC123')).toBeInTheDocument()
    expect(screen.getByText('24')).toBeInTheDocument()

    // Must NOT display literal <table> or </table> or <td> tags as text
    expect(screen.queryByText(/<table>/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/<\/table>/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/<tr>/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/<td>/i)).not.toBeInTheDocument()
  })

  // B. GFM Markdown table
  it('B. continues to render standard GFM markdown tables cleanly', () => {
    const gfmMarkdown = `
| Mã hàng | Đơn giá | Thành tiền |
| :--- | :---: | ---: |
| SP-99 | 150000 | 300000 |
`
    const { container } = render(<MarkdownPreview markdown={gfmMarkdown} />)

    const tableEl = container.querySelector('table')
    expect(tableEl).toBeInTheDocument()

    expect(screen.getByText('SP-99')).toBeInTheDocument()
    expect(screen.getByText('150000')).toBeInTheDocument()
    expect(screen.getByText('300000')).toBeInTheDocument()
  })

  // C. Unsafe HTML sanitization
  it('C. sanitizes unsafe HTML: removes script, iframe, onerror handlers, and javascript: protocols', () => {
    const unsafeMarkdown = `
# Security Test

<script>window.__pwned = true; alert('xss');</script>
<iframe src="https://attacker.example.com"></iframe>
<img src="https://example.com/logo.png" onerror="alert('img-xss')" alt="safe-logo" />
<a href="javascript:alert('link-xss')">Dangerous Link</a>
<button onclick="alert('click-xss')">Click me</button>
`
    const { container } = render(<MarkdownPreview markdown={unsafeMarkdown} />)

    // 1. Script tag must NOT exist in the DOM
    expect(container.querySelector('script')).toBeNull()

    // 2. iframe tag must NOT exist in the DOM
    expect(container.querySelector('iframe')).toBeNull()

    // 3. Img tag is rendered safely, but its onerror attribute must be stripped
    const imgEl = container.querySelector('img')
    expect(imgEl).toBeInTheDocument()
    expect(imgEl?.getAttribute('onerror')).toBeNull()

    // 4. Anchor tag with javascript: href must have its dangerous href completely stripped (null)
    const linkEl = container.querySelector('a')
    if (linkEl) {
      expect(linkEl.getAttribute('href')).toBeNull()
    }

    // 5. Button tag onclick must be stripped
    const buttonEl = container.querySelector('button')
    if (buttonEl) {
      expect(buttonEl.getAttribute('onclick')).toBeNull()
    }
  })

  // C2. Strips arbitrary inline styles while keeping safe attributes (colspan, rowspan)
  it('C2. strips arbitrary inline style attributes but preserves safe attributes like colspan and rowspan', () => {
    const tableWithStyles = `
<table>
  <tr>
    <th colspan="2" style="background-color: red; color: yellow;">Tiêu đề gộp</th>
  </tr>
  <tr>
    <td rowspan="2" style="text-align: center; word-wrap: break-word;">Ô gộp dòng</td>
    <td style="font-size: 50px;">Dữ liệu 1</td>
  </tr>
  <tr>
    <td>Dữ liệu 2</td>
  </tr>
</table>
`
    const { container } = render(<MarkdownPreview markdown={tableWithStyles} />)

    const th = container.querySelector('th')
    expect(th).toBeInTheDocument()
    // colspan preserved
    expect(th?.getAttribute('colspan')).toBe('2')
    // inline style stripped!
    expect(th?.getAttribute('style')).toBeNull()

    const tdRowSpan = container.querySelector('td[rowspan="2"]')
    expect(tdRowSpan).toBeInTheDocument()
    expect(tdRowSpan?.getAttribute('style')).toBeNull()
  })

  // D. Copy/Download Markdown in MarkdownTab is not affected by Preview rendering
  it('D. ensures raw markdown with HTML table remains unchanged for Copy and Download in MarkdownTab', async () => {
    const rawHtmlTableDoc = `# HÓA ĐƠN BÁN HÀNG

<table border="1" style="width:100%">
  <tr>
    <th>Tên hàng</th>
    <th>Số tiền</th>
  </tr>
  <tr>
    <td>Máy in HP LaserJet</td>
    <td>4.500.000 VNĐ</td>
  </tr>
</table>`

    const copySpy = vi.spyOn(utils, 'copyToClipboard').mockResolvedValue(true)
    const downloadSpy = vi.spyOn(utils, 'downloadFile').mockImplementation(() => {})

    render(<MarkdownTab markdown={rawHtmlTableDoc} filename="hoa_don.pdf" />)

    // Verify MarkdownTab displays the raw HTML as text
    expect(screen.getByText(/<table border="1" style="width:100%">/)).toBeInTheDocument()
    expect(screen.getByText(/Máy in HP LaserJet/)).toBeInTheDocument()

    // Test Copy button copies the exact raw markdown string
    const copyBtn = screen.getByRole('button', { name: /copy raw markdown to clipboard/i })
    await act(async () => {
      fireEvent.click(copyBtn)
    })

    expect(copySpy).toHaveBeenCalledWith(rawHtmlTableDoc)

    // Test Download button downloads the exact raw markdown string
    const downloadBtn = screen.getByRole('button', { name: /download markdown file/i })
    fireEvent.click(downloadBtn)

    expect(downloadSpy).toHaveBeenCalledWith(
      rawHtmlTableDoc,
      'hoa_don.md',
      'text/markdown'
    )

    copySpy.mockRestore()
    downloadSpy.mockRestore()
  })

  // E. Real OCR table format from output (1).md (10 columns, Vietnamese text, td-based header, colspan=6)
  it('E. renders real OCR output table with 10 columns, Vietnamese characters, and colspan correctly', () => {
    const realOcrMarkdown = `# PHIẾU XUẤT KHO KIÊM GIAO HÀNG

Tên nhà cung cấp: Công ty TNHH Một thành viên Kinh Đô Miền Bắc
Mã số đơn đặt hàng PO: 4174744145

<table border=1 style='margin: auto; word-wrap: break-word;'><tr><td style='text-align: center; word-wrap: break-word;'>Stt</td><td style='text-align: center; word-wrap: break-word;'>Mã hàng AD</td><td style='text-align: center; word-wrap: break-word;'>Mã hàng KH</td><td style='text-align: center; word-wrap: break-word;'>Mã vạch</td><td style='text-align: center; word-wrap: break-word;'>Tên hàng</td><td style='text-align: center; word-wrap: break-word;'>Đvt</td><td style='text-align: center; word-wrap: break-word;'>Số PO đặt</td><td style='text-align: center; word-wrap: break-word;'>Số xuất kho (IR)</td><td style='text-align: center; word-wrap: break-word;'>Thực nhận</td><td style='text-align: center; word-wrap: break-word;'>Ghi chú</td></tr><tr><td style='text-align: center; word-wrap: break-word;'>1</td><td style='text-align: center; word-wrap: break-word;'>4319201</td><td style='text-align: center; word-wrap: break-word;'>10014787</td><td style='text-align: center; word-wrap: break-word;'>7622300136055</td><td style='text-align: center; word-wrap: break-word;'>136055-ORÉO STRAWBERRY CREAM 24X110.4G</td><td style='text-align: center; word-wrap: break-word;'>Thanh</td><td style='text-align: center; word-wrap: break-word;'>24</td><td style='text-align: center; word-wrap: break-word;'></td><td style='text-align: center; word-wrap: break-word;'>24</td><td style='text-align: center; word-wrap: break-word;'></td></tr><tr><td colspan="6">Tổng cộng</td><td style='text-align: center; word-wrap: break-word;'>90</td><td style='text-align: center; word-wrap: break-word;'>90</td><td style='text-align: center; word-wrap: break-word;'></td><td style='text-align: center; word-wrap: break-word;'></td></tr></table>
`
    const { container } = render(<MarkdownPreview markdown={realOcrMarkdown} />)

    const tableEl = container.querySelector('table')
    expect(tableEl).toBeInTheDocument()

    // 10 columns are rendered
    expect(screen.getByText('Stt')).toBeInTheDocument()
    expect(screen.getByText('Mã hàng AD')).toBeInTheDocument()
    expect(screen.getByText('136055-ORÉO STRAWBERRY CREAM 24X110.4G')).toBeInTheDocument()

    // "Tổng cộng" cell has colspan="6"
    const tongCongCell = screen.getByText('Tổng cộng')
    expect(tongCongCell.getAttribute('colspan')).toBe('6')

    // No style attributes leaked
    expect(tongCongCell.getAttribute('style')).toBeNull()
    expect(tableEl?.getAttribute('style')).toBeNull()
  })
})

