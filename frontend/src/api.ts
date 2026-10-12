import { getMessages } from './i18n'
import type { Language } from './i18n'
import type { OCRResult } from './ocr'

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
  ) {
    super(getMessages('vi').errors[code])
    this.message = this.localizedMessage('vi')
  }

  localizedMessage(language: Language): string {
    const t = getMessages(language)
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
  const response = await fetch('/v1/ui/config', { signal, cache: 'no-store' })
  await assertResponse(response)
  const config: UIConfig = await response.json()
  if (
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
  const response = await fetch('/healthz', { signal, cache: 'no-store' })
  return response.ok && (await response.json()).status === 'ok'
}

export async function runOCR(file: File, signal: AbortSignal): Promise<OCRResult> {
  const body = new FormData()
  body.append('file', file)
  const response = await fetch('/v1/doc/ocr/result?include_preview=true', {
    method: 'POST',
    body,
    signal,
  })
  await assertResponse(response)
  if (!response.headers.get('Content-Type')?.toLowerCase().startsWith('application/json')) {
    throw new UIError('invalidOCR')
  }
  let result: OCRResult
  try {
    result = await response.json()
  } catch {
    throw new UIError('invalidOCR')
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
