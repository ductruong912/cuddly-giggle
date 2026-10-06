export interface UIConfig {
  supported_suffixes: string[]
  max_upload_bytes: number
  pdf_max_pages: number
}

const errorMessages: Record<number, string> = {
  400: 'Tài liệu hoặc yêu cầu không hợp lệ. Hãy kiểm tra file rồi thử lại.',
  413: 'Tài liệu vượt giới hạn dung lượng hoặc số trang OCR của máy chủ.',
  415: 'Định dạng gửi lên không được hỗ trợ.',
  422: 'Không đọc được nội dung Markdown. Hãy kiểm tra tài liệu rồi thử lại.',
  429: 'Bạn gửi yêu cầu quá nhanh. Hãy chờ một chút rồi thử lại.',
  503: 'Dịch vụ OCR đang bận hoặc chưa sẵn sàng. Hãy thử lại sau.',
  504: 'OCR đã hết thời gian chờ. Máy chủ có thể vẫn đang xử lý tài liệu.',
}

async function assertResponse(response: Response): Promise<void> {
  if (response.ok) return
  const retry = response.headers.get('Retry-After')
  const seconds =
    retry && /^\d+$/.test(retry) ? ` Chờ ít nhất ${retry} giây trước khi thử lại.` : ''
  throw new Error(
    (errorMessages[response.status] ?? 'Máy chủ gặp lỗi khi xử lý yêu cầu.') + seconds,
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
    throw new Error('Cấu hình upload của máy chủ không hợp lệ.')
  }
  return config
}

export async function checkHealth(signal: AbortSignal): Promise<boolean> {
  const response = await fetch('/healthz', { signal, cache: 'no-store' })
  return response.ok && (await response.json()).status === 'ok'
}

export async function runOCR(file: File, signal: AbortSignal): Promise<string> {
  const body = new FormData()
  body.append('file', file)
  const response = await fetch('/v1/doc/ocr', { method: 'POST', body, signal })
  await assertResponse(response)
  if (!response.headers.get('Content-Type')?.toLowerCase().startsWith('text/markdown')) {
    throw new Error('Máy chủ trả về nội dung không đúng định dạng Markdown.')
  }
  const markdown = await response.text()
  if (!markdown.trim()) throw new Error('Không tìm thấy nội dung trong kết quả OCR.')
  return markdown
}

export function fileSuffix(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot).toLowerCase()
}

export function formatBytes(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} MB`
    : `${(bytes / 1024).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} KB`
}

export function validateFile(file: File, config: UIConfig): string | null {
  if (!config.supported_suffixes.includes(fileSuffix(file.name))) {
    return 'Định dạng file chưa được hỗ trợ. Hãy chọn PDF, Word, Excel hoặc ảnh.'
  }
  if (file.size === 0) return 'File đang trống. Hãy chọn một tài liệu có nội dung.'
  if (file.size > config.max_upload_bytes)
    return `File vượt giới hạn ${formatBytes(config.max_upload_bytes)}.`
  return null
}
