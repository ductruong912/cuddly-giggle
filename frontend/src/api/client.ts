import { ApiError, parseErrorResponse } from './errors'
import type {
  ExtractionListResponse,
  ExtractionRecord,
  HealthzResponse,
  LLMExtractionResponse,
  ReadyzResponse,
} from '@/types/api'

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  let response: Response
  try {
    response = await fetch(endpoint, options)
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, 'Request was cancelled by user.', undefined, true)
    }
    throw new ApiError(
      0,
      'Network error. Could not connect to backend server. Make sure the API server is running on http://127.0.0.1:8000.'
    )
  }

  // Handle special case: /readyz returns 503 when not ready, but still returns JSON content!
  if (endpoint.startsWith('/readyz')) {
    const data = await response.json().catch(() => null)
    if (data && (response.status === 200 || response.status === 503)) {
      return data as T
    }
  }

  if (!response.ok) {
    let errorBody: unknown
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      errorBody = await response.json().catch(() => null)
    } else {
      errorBody = await response.text().catch(() => null)
    }
    throw parseErrorResponse(response.status, errorBody)
  }

  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return (await response.json()) as T
  }
  return (await response.text()) as unknown as T
}

export const apiClient = {
  /**
   * Run local OCR on the document and return Markdown.
   * Route: POST /v1/doc/ocr
   */
  async ocrDocument(file: File, signal?: AbortSignal): Promise<string> {
    const formData = new FormData()
    formData.append('file', file)

    return request<string>('/v1/doc/ocr', {
      method: 'POST',
      body: formData,
      signal,
    })
  },

  /**
   * Run local OCR + structured Purchase Order extraction.
   * Route: POST /v1/extract/local
   */
  async extractLocal(file: File, signal?: AbortSignal): Promise<LLMExtractionResponse> {
    const formData = new FormData()
    formData.append('file', file)

    return request<LLMExtractionResponse>('/v1/extract/local', {
      method: 'POST',
      body: formData,
      signal,
    })
  },

  /**
   * Run online OCR + structured extraction (if supported).
   * Route: POST /v1/extract/online
   */
  async extractOnline(file: File, signal?: AbortSignal): Promise<LLMExtractionResponse> {
    const formData = new FormData()
    formData.append('file', file)

    return request<LLMExtractionResponse>('/v1/extract/online', {
      method: 'POST',
      body: formData,
      signal,
    })
  },

  /**
   * Check liveness.
   * Route: GET /healthz
   */
  async getHealth(signal?: AbortSignal): Promise<HealthzResponse> {
    return request<HealthzResponse>('/healthz', {
      method: 'GET',
      signal,
    })
  },

  /**
   * Check readiness.
   * Route: GET /readyz
   */
  async getReadiness(signal?: AbortSignal): Promise<ReadyzResponse> {
    return request<ReadyzResponse>('/readyz', {
      method: 'GET',
      signal,
    })
  },

  /**
   * List past extractions (when persistence is enabled).
   * Route: GET /v1/extractions
   */
  async getExtractions(
    params: {
      limit?: number
      offset?: number
      status?: string
      po_number?: string
    } = {},
    signal?: AbortSignal
  ): Promise<ExtractionListResponse> {
    const query = new URLSearchParams()
    if (params.limit !== undefined) query.set('limit', String(params.limit))
    if (params.offset !== undefined) query.set('offset', String(params.offset))
    if (params.status) query.set('status', params.status)
    if (params.po_number) query.set('po_number', params.po_number)

    const qs = query.toString()
    return request<ExtractionListResponse>(`/v1/extractions${qs ? `?${qs}` : ''}`, {
      method: 'GET',
      signal,
    })
  },

  /**
   * Fetch one extraction record by request_id.
   * Route: GET /v1/extractions/{request_id}
   */
  async getExtraction(requestId: string, signal?: AbortSignal): Promise<ExtractionRecord> {
    return request<ExtractionRecord>(`/v1/extractions/${encodeURIComponent(requestId)}`, {
      method: 'GET',
      signal,
    })
  },
}
