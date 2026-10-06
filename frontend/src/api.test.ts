import { describe, expect, it, vi } from 'vitest'
import { fetchConfig, runOCR, validateFile } from './api'

const config = {
  supported_suffixes: ['.pdf', '.png', '.docx'],
  max_upload_bytes: 100,
  pdf_max_pages: 2,
}

describe('OCR requests', () => {
  it('uploads only to OCR and preserves the exact Markdown response', async () => {
    const text = '# Nội dung\n\n| A | B |\n|---|---|\n|1|2|\n'
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(text, { headers: { 'Content-Type': 'text/markdown; charset=utf-8' } }),
      )
    vi.stubGlobal('fetch', fetch)
    const file = new File(['pdf'], 'test.pdf')
    const signal = new AbortController().signal
    expect(await runOCR(file, signal)).toBe(text)
    expect(fetch).toHaveBeenCalledTimes(1)
    const [path, options] = fetch.mock.calls[0]
    expect(path).toBe('/v1/doc/ocr')
    expect(options.signal).toBe(signal)
    expect(options.method).toBe('POST')
    expect((options.body as FormData).get('file')).toBe(file)
    expect(options.headers).toBeUndefined() // Browser supplies the multipart boundary.
  })

  it.each([400, 413, 415, 422, 429, 503, 504, 500])(
    'handles HTTP %s without retrying',
    async (status) => {
      const fetch = vi.fn().mockResolvedValue(
        new Response('{"detail":"private server data"}', {
          status,
          headers: { 'Retry-After': '7' },
        }),
      )
      vi.stubGlobal('fetch', fetch)
      await expect(
        runOCR(new File(['x'], 'test.pdf'), new AbortController().signal),
      ).rejects.toThrow('7 giây')
      expect(fetch).toHaveBeenCalledTimes(1)
    },
  )

  it.each([
    new Response('<html>proxy error</html>', { headers: { 'Content-Type': 'text/html' } }),
    new Response('  ', { headers: { 'Content-Type': 'text/markdown' } }),
  ])('rejects unusable successful responses', async (response) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    await expect(
      runOCR(new File(['x'], 'test.pdf'), new AbortController().signal),
    ).rejects.toThrow()
  })
})

describe('upload configuration', () => {
  it('accepts uppercase suffixes, rejects unsupported, empty and oversized files', () => {
    expect(validateFile(new File(['x'], 'scan.PDF'), config)).toBeNull()
    expect(validateFile(new File(['x'], 'note.md'), config)?.message).toContain('Định dạng')
    expect(validateFile(new File([], 'empty.pdf'), config)?.message).toContain('trống')
    expect(validateFile(new File(['x'.repeat(101)], 'large.pdf'), config)?.message).toContain(
      'giới hạn',
    )
  })

  it('does not reject PDF based on page count at the browser', () => {
    expect(validateFile(new File(['synthetic long native PDF'], 'long.pdf'), config)).toBeNull()
  })

  it('refuses malformed server configuration', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...config, max_upload_bytes: -1 }))),
    )
    await expect(fetchConfig(new AbortController().signal)).rejects.toThrow('không hợp lệ')
  })
})
