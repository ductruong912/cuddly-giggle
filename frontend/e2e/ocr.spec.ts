import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const markdown =
  '# Biên bản giao nhận\n\nTài liệu tổng hợp dùng để kiểm thử.\n\n| Hạng mục | Số lượng |\n|---|---:|\n| Tài liệu A | 12 |\n| Tài liệu B | 8 |\n\n**Ghi chú:** Đã kiểm tra nội dung.\n'
const config = {
  supported_suffixes: [
    '.pdf',
    '.doc',
    '.docx',
    '.xls',
    '.xlsx',
    '.xlsm',
    '.png',
    '.jpg',
    '.jpeg',
    '.bmp',
    '.webp',
    '.tif',
    '.tiff',
  ],
  max_upload_bytes: 50 * 1024 * 1024,
  pdf_max_pages: 100,
}

// Minimal two-page PDF with calculated byte offsets; no customer documents.
function syntheticPDF() {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ...['SYNTHETIC DOCUMENT - PAGE 1', 'SYNTHETIC DOCUMENT - PAGE 2'].map((title) => {
      const stream = `BT /F1 22 Tf 50 750 Td (${title}) Tj 0 -40 Td /F1 12 Tf (OCR Playground - browser test fixture) Tj ET`
      return `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`
    }),
  ]
  let data = '%PDF-1.4\n'
  const offsets = [0]
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(data))
    data += `${index + 1} 0 obj\n${object}\nendobj\n`
  })
  const xref = Buffer.byteLength(data)
  data += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  data += offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`)
    .join('')
  data += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`
  return Buffer.from(data)
}

async function mockReadEndpoints(page: Page) {
  await page.route('**/v1/ui/config', (route) => route.fulfill({ json: config }))
  await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/v1/extract/**', () => {
    throw new Error('The OCR UI must never call extraction')
  })
}

for (const width of [1440, 390]) {
  test(`theme/language settings in a collapsible sidebar at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 960 })
    await page.emulateMedia({ colorScheme: 'dark' })
    await mockReadEndpoints(page)
    let requests = 0
    await page.route('**/v1/doc/ocr', (route) => {
      requests++
      return route.fulfill({ contentType: 'text/markdown', body: markdown })
    })
    await page.goto('/')
    const root = page.locator('html')
    const settings = page.locator('#preferences')
    await expect(root).toHaveAttribute('data-theme', 'dark')
    await expect(page.getByRole('button', { name: 'Tài liệu mới' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Cài đặt' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Mở thanh bên' }).click()
    await expect(settings).toBeVisible()
    await expect(page.getByRole('radio', { name: 'Hệ thống', exact: true })).toBeChecked()
    await page.getByRole('radio', { name: 'Sáng', exact: true }).check()
    await expect(root).toHaveAttribute('data-theme', 'light')
    await page.getByRole('radio', { name: 'Tối', exact: true }).check()
    await expect(root).toHaveAttribute('data-theme', 'dark')
    await page.emulateMedia({ colorScheme: 'light' })
    await expect(root).toHaveAttribute('data-theme', 'dark')
    await page.getByRole('radio', { name: 'Hệ thống', exact: true }).check()
    await expect(root).toHaveAttribute('data-theme', 'light')
    await page.emulateMedia({ colorScheme: 'dark' })
    await expect(root).toHaveAttribute('data-theme', 'dark')
    await page.getByLabel('Ngôn ngữ', { exact: true }).selectOption('en')
    await expect(root).toHaveAttribute('lang', 'en')
    await expect(page.getByRole('button', { name: 'Connected', exact: true })).toBeVisible()
    await page.getByRole('radio', { name: 'System', exact: true }).focus()
    await page.keyboard.press('Escape')
    await expect(settings).toBeHidden()
    await expect(page.getByRole('button', { name: 'Open sidebar', exact: true })).toBeFocused()
    await page.getByLabel('Choose document', { exact: true }).setInputFiles({
      name: 'synthetic.pdf',
      mimeType: 'application/pdf',
      buffer: syntheticPDF(),
    })
    await expect(page.getByText('Page 1 / 2')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Zoom in', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Read document', exact: true }).click()
    await expect(page.getByRole('table')).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Tài liệu A' })).toBeVisible()
    const before = (await page.locator('.workspace').boundingBox())!
    await page.getByRole('button', { name: 'Open sidebar', exact: true }).click()
    const sidebar = page.getByRole('complementary', { name: 'Sidebar', exact: true })
    await expect(sidebar).toBeVisible()
    await expect(sidebar.locator('nav')).toHaveCount(0)
    const after = (await page.locator('.workspace').boundingBox())!
    if (width >= 960) expect(before.width - after.width).toBeGreaterThan(150)
    else expect(Math.abs(before.width - after.width)).toBeLessThan(1)
    await page.screenshot({
      path: testInfo.outputPath(`sidebar-dark-${width}.png`),
      fullPage: true,
    })
    await page.keyboard.press('Escape')
    await expect(sidebar).toBeHidden()
    await expect(page.getByRole('button', { name: 'Open sidebar', exact: true })).toBeFocused()
    await page.getByRole('button', { name: 'Open sidebar', exact: true }).click()
    await page.screenshot({
      path: testInfo.outputPath(`settings-dark-${width}.png`),
      fullPage: true,
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.getByLabel('Language', { exact: true }).selectOption('vi')
    await expect(page.getByRole('tab', { name: 'Trình bày', exact: true })).toBeVisible()
    await page.getByLabel('Ngôn ngữ', { exact: true }).selectOption('en')
    expect(requests).toBe(1)
    await page.reload()
    await expect(root).toHaveAttribute('lang', 'en')
    await expect(root).toHaveAttribute('data-theme', 'dark')
    await page.getByRole('button', { name: 'Open sidebar', exact: true }).click()
    await expect(page.getByRole('radio', { name: 'System', exact: true })).toBeChecked()
    await sidebar.getByRole('button', { name: 'Close sidebar', exact: true }).click()
    await expect(settings).toBeHidden()
  })
}

test('OCR flow, PDF pagination/zoom, clipboard, exact download and file replacement', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await mockReadEndpoints(page)
  let count = 0
  let finish!: () => void
  const pending = new Promise<void>((resolve) => {
    finish = resolve
  })
  await page.route('**/v1/doc/ocr', async (route) => {
    count++
    expect(route.request().method()).toBe('POST')
    expect(route.request().headers()['content-type']).toContain('multipart/form-data; boundary=')
    expect(route.request().postDataBuffer()?.toString()).toContain('name="file"')
    await pending
    await route.fulfill({ contentType: 'text/markdown; charset=utf-8', body: markdown })
  })
  await page.goto('/playground')
  await expect(page.getByRole('button', { name: 'Đọc tài liệu' })).toHaveCount(0)
  const input = page.getByLabel('Chọn tài liệu', { exact: true })
  await expect(input).toBeEnabled()
  await input.setInputFiles({
    name: 'synthetic.pdf',
    mimeType: 'application/pdf',
    buffer: syntheticPDF(),
  })
  await expect(page.getByText('Trang 1 / 2')).toBeVisible()
  await expect(page.locator('.preview-loading')).toHaveCount(0)
  const workspace = await page.locator('.workspace').boundingBox()
  const original = await page.locator('.pdf-canvas').boundingBox()
  expect(workspace!.width).toBeGreaterThan(1800)
  expect(original!.width).toBeGreaterThan(850)
  const documentPanel = page.locator('#panel-document')
  const resultPanel = page.locator('#panel-result')
  expect(
    Math.abs((await documentPanel.boundingBox())!.width - (await resultPanel.boundingBox())!.width),
  ).toBeLessThan(1)
  const divider = page.getByRole('separator')
  await expect(divider).toHaveAttribute('aria-valuenow', '50')
  const splitBounds = (await page.locator('.workspace-panels').boundingBox())!
  const handle = (await divider.boundingBox())!
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
  await page.mouse.down()
  await page.mouse.move(splitBounds.x + splitBounds.width * 0.65, handle.y + handle.height / 2, {
    steps: 12,
  })
  await expect(divider).toHaveAttribute('aria-valuenow', '65')
  await expect
    .poll(async () => (await page.locator('.pdf-canvas').boundingBox())!.width)
    .toBeGreaterThan(original!.width + 200)
  await page.mouse.move(splitBounds.x + splitBounds.width + 10, handle.y + handle.height / 2)
  await expect(divider).toHaveAttribute('aria-valuenow', '75')
  await page.mouse.move(splitBounds.x - 10, handle.y + handle.height / 2)
  await expect(divider).toHaveAttribute('aria-valuenow', '25')
  await page.mouse.up()
  await expect(page.locator('.workspace-panels')).not.toHaveClass(/is-resizing/)
  await divider.dblclick()
  await expect(divider).toHaveAttribute('aria-valuenow', '50')
  expect(
    await page.locator('.pdf-canvas').evaluate((element) => {
      const canvas = element as HTMLCanvasElement
      const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data
      return pixels.some((value, index) => index % 4 === 0 && value < 100 && pixels[index + 3] > 0)
    }),
  ).toBe(true)
  await page.getByRole('button', { name: 'Trang sau' }).click()
  await expect(page.getByText('Trang 2 / 2')).toBeVisible()
  await page.getByRole('button', { name: 'Phóng to', exact: true }).click()
  await expect(page.getByText('125%')).toBeVisible()
  await page.getByRole('button', { name: 'Đọc tài liệu' }).click()
  await expect(page.getByRole('button', { name: 'Đang xử lý…', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Đổi file' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Mở thanh bên' })).toBeEnabled()
  finish()
  await expect(page.getByRole('table')).toBeVisible()
  await page.getByRole('button', { name: 'Thu nhỏ', exact: true }).click()
  await expect(page.getByText('100%')).toBeVisible()
  await expect
    .poll(() =>
      page.locator('.pdf-canvas').evaluate((canvas) => {
        const scroll = canvas.parentElement!
        const style = getComputedStyle(scroll)
        const available =
          scroll.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
        return Math.abs(canvas.getBoundingClientRect().width - available)
      }),
    )
    .toBeLessThan(1)
  await expect(page.locator('.preview-loading')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('pdf-comparison-1920.png'), fullPage: true })
  expect(count).toBe(1)
  await page.getByRole('tab', { name: 'Markdown', exact: true }).click()
  await expect(page.locator('.markdown-source')).toHaveText(markdown)
  await page.bringToFront()
  // Record the exact payload after a successful native write. Windows host clipboard
  // reads can return empty text in browser automation even when the write succeeds.
  await page.evaluate(() => {
    const write = navigator.clipboard.writeText.bind(navigator.clipboard)
    navigator.clipboard.writeText = async (text) => {
      await write(text)
      Object.assign(window, { lastClipboardWrite: text })
    }
  })
  await page.getByRole('button', { name: 'Sao chép Markdown' }).click()
  await expect(page.locator('.copy-toast')).toHaveText('Đã sao chép')
  expect(
    await page.evaluate(
      () => (window as Window & { lastClipboardWrite?: string }).lastClipboardWrite,
    ),
  ).toBe(markdown)
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Tải Markdown' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('synthetic.md')
  const stream = await download.createReadStream()
  const chunks = []
  for await (const chunk of stream!) chunks.push(chunk)
  expect(Buffer.concat(chunks).toString('utf-8')).toBe(markdown)
  await input.setInputFiles({
    name: 'table.xlsx',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('synthetic office'),
  })
  await expect(
    page.getByText('Chưa hỗ trợ xem trước định dạng này.', { exact: false }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sao chép Markdown' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Tài liệu mới' })).toHaveCount(0)
  expect(errors).toEqual([])
})

for (const width of [1440, 768, 390, 320]) {
  test(`workspace and result fit ${width}px with keyboard/mobile navigation`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 960 })
    await mockReadEndpoints(page)
    await page.route('**/v1/doc/ocr', (route) =>
      route.fulfill({ contentType: 'text/markdown', body: markdown }),
    )
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Đã kết nối' })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`empty-${width}.png`), fullPage: true })
    const input = page.getByLabel('Chọn tài liệu', { exact: true })
    await input.setInputFiles({
      name: 'document.docx',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('synthetic'),
    })
    await page.getByRole('button', { name: 'Đọc tài liệu' }).click()
    await expect(page.getByRole('table')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Tải Markdown' })).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`result-${width}.png`), fullPage: true })
    if (width >= 960) {
      await page.getByRole('separator').press('End')
      await expect(page.getByRole('separator')).toHaveAttribute('aria-valuenow', '75')
      await expect(page.getByRole('tab', { name: 'Markdown' })).toBeVisible()
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true)
      await page.getByRole('separator').press('Enter')
    }
    const tab = page.getByRole('tab', { name: 'Trình bày' })
    await tab.focus()
    await page.keyboard.press('ArrowRight')
    await expect(page.getByRole('tab', { name: 'Markdown' })).toBeFocused()
    if (width < 960) {
      await expect(page.getByRole('separator')).toHaveCount(0)
      await page.getByRole('tab', { name: 'Bản gốc', exact: true }).click()
      await expect(page.locator('.file-fallback')).toBeVisible()
    }
  })
}

test('HTTP failure, explicit retry, image preview and blocked remote images/HTML', async ({
  page,
}) => {
  await mockReadEndpoints(page)
  let count = 0
  let remoteRequests = 0
  await page.route('https://example.com/**', (route) => {
    remoteRequests++
    return route.abort()
  })
  await page.route('**/v1/doc/ocr', (route) => {
    count++
    return count === 1
      ? route.fulfill({ status: 503, json: { detail: 'busy' }, headers: { 'Retry-After': '3' } })
      : route.fulfill({
          contentType: 'text/markdown',
          body: '# Safe\n\n![external](https://example.com/image.png)\n\n<img src="https://example.com/html.png" onerror="window.injected=true" />\n<script>window.injected=true</script>\n\n<table onclick="window.injected=true" style="background:url(https://example.com/style)"><tr><th colspan="2">Hàng hóa</th></tr><tr><td>Tài liệu A</td><td>12</td></tr></table>',
        })
  })
  await page.goto('/')
  const input = page.getByLabel('Chọn tài liệu', { exact: true })
  await expect(input).toBeEnabled()
  await input.setInputFiles({
    name: 'scan.png',
    mimeType: 'image/png',
    buffer: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6S4AAAAAASUVORK5CYII=',
      'base64',
    ),
  })
  await expect(page.locator('.image-preview')).toBeVisible()
  await page.getByRole('button', { name: 'Phóng to', exact: true }).click()
  await expect(page.getByText('125%')).toBeVisible()
  await page.getByRole('button', { name: 'Đọc tài liệu' }).click()
  await expect(page.getByRole('alert')).toContainText('3 giây')
  expect(count).toBe(1)
  await page.getByRole('button', { name: 'Thử lại' }).click()
  await expect(page.getByText('[Ảnh: external]')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Tài liệu A' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Hàng hóa' })).toHaveAttribute('colspan', '2')
  await expect(page.locator('.markdown-content [onclick], .markdown-content [style]')).toHaveCount(
    0,
  )
  expect(remoteRequests).toBe(0)
  await expect(page.locator('.markdown-content img, .markdown-content script')).toHaveCount(0)
})
