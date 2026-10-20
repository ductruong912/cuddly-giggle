import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ocrFixture } from '../fixtures/ocrFixture'

const mock = vi.hoisted(() => ({ connect: vi.fn(), submit: vi.fn(), handleFile: vi.fn() }))
vi.mock('@gradio/client', () => ({
  Client: { connect: mock.connect },
  handle_file: mock.handleFile,
}))

function response(value: unknown) {
  return {
    cancel: vi.fn().mockResolvedValue(undefined),
    async *[Symbol.asyncIterator]() {
      yield { type: 'data', data: [value] }
    },
  }
}

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_GRADIO_SPACE', 'demo/ocr')
  mock.connect.mockResolvedValue({ submit: mock.submit })
  mock.handleFile.mockImplementation((file: File) => ({ uploaded: file }))
})
afterEach(() => vi.unstubAllEnvs())

describe('ZeroGPU transport', () => {
  it('connects to the current React origin in the single-Space deployment', async () => {
    vi.stubEnv('VITE_GRADIO_SPACE', 'self')
    mock.submit.mockReturnValue(response(ocrFixture('# Same Space')))
    const { runOCR } = await import('./api')
    await runOCR(new File(['scan'], 'scan.pdf'), new AbortController().signal)
    expect(mock.connect).toHaveBeenCalledWith(window.location.origin, {
      record_history: false, events: ['data', 'status'],
    })
  })
  it('uploads through Gradio and preserves JSON, previews, and exact Markdown', async () => {
    const payload = ocrFixture('# Demo\n\n| A | B |\n|---|---|\n|1|2|\n')
    mock.submit.mockReturnValue(response(payload))
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const { runOCR } = await import('./api')
    const file = new File(['scan'], 'scan.pdf')
    expect(await runOCR(file, new AbortController().signal)).toEqual(payload)
    expect(mock.connect).toHaveBeenCalledWith('demo/ocr', {
      record_history: false, events: ['data', 'status'],
    })
    expect(mock.submit).toHaveBeenCalledWith('/ocr', [{ uploaded: file }])
    expect(fetch).not.toHaveBeenCalled()
  })

  it('gets authoritative upload limits through the CPU configuration endpoint', async () => {
    const config = { supported_suffixes: ['.pdf'], max_upload_bytes: 2048, pdf_max_pages: 3 }
    mock.submit.mockReturnValue(response(config))
    const { fetchConfig, checkHealth } = await import('./api')
    expect(await fetchConfig(new AbortController().signal)).toEqual(config)
    expect(await checkHealth(new AbortController().signal)).toBe(true)
    expect(mock.connect).toHaveBeenCalledTimes(1)
    expect(mock.submit.mock.calls.every(([endpoint]) => endpoint === '/ui_config')).toBe(true)
  })

  it('reports quota exhaustion without resubmitting an inference job', async () => {
    mock.submit.mockReturnValue({
      cancel: vi.fn(),
      async *[Symbol.asyncIterator]() {
        yield { type: 'status', stage: 'error', message: 'GPU quota exceeded' }
      },
    })
    const { runOCR } = await import('./api')
    await expect(runOCR(new File(['x'], 'x.png'), new AbortController().signal))
      .rejects.toMatchObject({ code: 'gpuQuota' })
    expect(mock.submit).toHaveBeenCalledTimes(1)
  })

  it('shows remaining quota instead of claiming it is exhausted when the reservation is too large', async () => {
    mock.submit.mockReturnValue({
      cancel: vi.fn(),
      async *[Symbol.asyncIterator]() {
        yield {
          type: 'status', stage: 'error',
          message: 'You have exceeded your ZeroGPU quota (180s requested vs. 177s left). Try again in 23:55:13.',
        }
      },
    })
    const { runOCR } = await import('./api')
    await expect(runOCR(new File(['x'], 'x.png'), new AbortController().signal))
      .rejects.toMatchObject({
        code: 'gpuQuota',
        gpuQuota: { requested: 180, remaining: 177, resetIn: '23:55:13' },
        message: expect.stringContaining('180'),
      })
  })

  it('cancels the queued Gradio job when the request is aborted', async () => {
    let finish!: () => void
    let started!: () => void
    const waiting = new Promise<void>((resolve) => { finish = resolve })
    const ready = new Promise<void>((resolve) => { started = resolve })
    const job = {
      cancel: vi.fn().mockImplementation(async () => { finish() }),
      async *[Symbol.asyncIterator]() {
        started()
        await waiting
        yield { type: 'data', data: [ocrFixture('# Cancelled')] }
      },
    }
    mock.submit.mockReturnValue(job)
    const { runOCR } = await import('./api')
    const controller = new AbortController()
    const result = runOCR(new File(['x'], 'x.png'), controller.signal)
    const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' })
    await ready
    controller.abort()
    await rejected
    expect(job.cancel).toHaveBeenCalledTimes(1)
  })

  it('rejects malformed OCR even when the Gradio request succeeds', async () => {
    mock.submit.mockReturnValue(response({ markdown: 'missing pages and blocks' }))
    const { runOCR } = await import('./api')
    await expect(runOCR(new File(['x'], 'x.png'), new AbortController().signal))
      .rejects.toMatchObject({ code: 'invalidOCR' })
  })
})
