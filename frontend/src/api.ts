import { getMessages } from './i18n'
import type { Language } from './i18n'
import type { OCRResult } from './ocr'

const gradioTarget = import.meta.env.VITE_GRADIO_SPACE?.trim()
const gradioSpace = gradioTarget === 'self' ? window.location.origin : gradioTarget
let demoClient: Promise<import('@gradio/client').Client> | undefined

async function demoRequest(endpoint: string, signal: AbortSignal, file?: File): Promise<unknown> {
  signal.throwIfAborted()
  const { Client, handle_file } = await import('@gradio/client')
  demoClient ??= Client.connect(gradioSpace!, {
    record_history: false,
    events: ['data', 'status'],
  }).catch((error) => {
    demoClient = undefined
    throw error
  })
  const client = await demoClient
  signal.throwIfAborted()
  const job = client.submit(endpoint, file ? [handle_file(file)] : [])
  const cancel = () => { void job.cancel().catch(() => {}) }
  signal.addEventListener('abort', cancel, { once: true })
  try {
    for await (const event of job) {
      signal.throwIfAborted()
      if (event.type === 'status' && event.stage === 'error') {
        const message = typeof event.message === 'string' ? event.message : ''
        if (/quota|exceeded.*GPU/i.test(message)) {
          const amounts = message.match(/(\d+(?:\.\d+)?)s requested vs\.\s*(\d+(?:\.\d+)?)s left/i)
          const resetIn = message.match(/Try again in (\d{1,3}:\d{2}:\d{2})/i)?.[1]
          throw new UIError('gpuQuota', undefined, undefined, amounts ? {
            requested: Number(amounts[1]), remaining: Number(amounts[2]), resetIn,
          } : undefined)
        }
        throw new UIError('http503')
      }
      if (event.type === 'data') return event.data[0]
    }
    signal.throwIfAborted()
    throw new UIError('invalidOCR')
  } finally {
    signal.removeEventListener('abort', cancel)
  }
}

export interface UIConfig {
  supported_suffixes: string[]
  max_upload_bytes: number
  pdf_max_pages: number
}

type ErrorCode = keyof ReturnType<typeof getMessages>['errors']
const errorCodes: Record<number, ErrorCode> = {
  400: 'http400',
  413: 'http413',
  415: 'http415',
  422: 'http422',
  429: 'http429',
  503: 'http503',
  504: 'http504',
}

export class UIError extends Error {
  constructor(
    readonly code: ErrorCode,
    readonly limitBytes?: number,
    readonly retryAfter?: string,
    readonly gpuQuota?: { requested: number; remaining: number; resetIn?: string },
  ) {
    super(getMessages('vi').errors[code])
    this.message = this.localizedMessage('vi')
  }

  localizedMessage(language: Language): string {
    const t = getMessages(language)
    if (this.code === 'gpuQuota' && this.gpuQuota) {
      return t.gpuQuotaDetails(this.gpuQuota.requested, this.gpuQuota.remaining, this.gpuQuota.resetIn)
    }
    return (
      t.errors[this.code] +
      (this.limitBytes === undefined ? '' : ` ${formatBytes(this.limitBytes, language)}.`) +
      (this.retryAfter ? t.retryAfter(this.retryAfter) : '')
    )
  }
}

async function assertResponse(response: Response): Promise<void> {
  if (response.ok) return
  const retry = response.headers.get('Retry-After')
  throw new UIError(
    errorCodes[response.status] ?? 'serverError',
    undefined,
    retry && /^\d+$/.test(retry) ? retry : undefined,
  )
}

export async function fetchConfig(signal: AbortSignal): Promise<UIConfig> {
  let config: UIConfig
  if (gradioSpace) {
    config = await demoRequest('/ui_config', signal) as UIConfig
  } else {
    const response = await fetch('/v1/ui/config', { signal, cache: 'no-store' })
    await assertResponse(response)
    config = await response.json()
  }
  if (
    !config ||
    !Array.isArray(config.supported_suffixes) ||
    !config.supported_suffixes.length ||
    !config.supported_suffixes.every(
      (value) => typeof value === 'string' && value.startsWith('.'),
    ) ||
    !Number.isSafeInteger(config.max_upload_bytes) ||
    config.max_upload_bytes <= 0 ||
    !Number.isSafeInteger(config.pdf_max_pages) ||
    config.pdf_max_pages <= 0
  ) {
    throw new UIError('invalidConfig')
  }
  return config
}

export async function checkHealth(signal: AbortSignal): Promise<boolean> {
  if (gradioSpace) {
    await fetchConfig(signal)
    return true
  }
  const response = await fetch('/healthz', { signal, cache: 'no-store' })
  return response.ok && (await response.json()).status === 'ok'
}

export async function runOCR(file: File, signal: AbortSignal): Promise<OCRResult> {
  let result: OCRResult
  if (gradioSpace) {
    result = await demoRequest('/ocr', signal, file) as OCRResult
  } else {
    const body = new FormData()
    body.append('file', file)
    const response = await fetch('/v1/doc/ocr/result?include_preview=true', {
      method: 'POST', body, signal,
    })
    await assertResponse(response)
    if (!response.headers.get('Content-Type')?.toLowerCase().startsWith('application/json')) {
      throw new UIError('invalidOCR')
    }
    try {
      result = await response.json()
    } catch {
      throw new UIError('invalidOCR')
    }
  }
  if (
    !result ||
    typeof result.markdown !== 'string' ||
    !Array.isArray(result.pages) ||
    !Array.isArray(result.blocks) ||
    !Array.isArray(result.tables) ||
    !Array.isArray(result.reading_order)
  ) {
    throw new UIError('invalidOCR')
  }
  if (!result.markdown.trim()) throw new UIError('emptyOCR')
  return result
}

export function fileSuffix(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot).toLowerCase()
}

export function formatBytes(bytes: number, language: Language = 'vi'): string {
  const locale = language === 'vi' ? 'vi-VN' : 'en-US'
  return bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toLocaleString(locale, { maximumFractionDigits: 1 })} MB`
    : `${(bytes / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} KB`
}

export function validateFile(file: File, config: UIConfig): UIError | null {
  if (!config.supported_suffixes.includes(fileSuffix(file.name))) {
    return new UIError('fileUnsupported')
  }
  if (file.size === 0) return new UIError('fileEmpty')
  if (file.size > config.max_upload_bytes)
    return new UIError('fileTooLarge', config.max_upload_bytes)
  return null
}
