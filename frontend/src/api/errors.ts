export class ApiError extends Error {
  public status: number
  public detail?: string
  public isAborted: boolean

  constructor(status: number, message: string, detail?: string, isAborted = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.isAborted = isAborted
  }
}

export function parseErrorResponse(status: number, responseBody: unknown): ApiError {
  let detail: string | undefined

  if (typeof responseBody === 'string') {
    detail = responseBody
  } else if (responseBody && typeof responseBody === 'object') {
    const errorObj = responseBody as { detail?: unknown; message?: string }
    if (typeof errorObj.detail === 'string') {
      detail = errorObj.detail
    } else if (Array.isArray(errorObj.detail)) {
      detail = errorObj.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
    } else if (errorObj.message) {
      detail = errorObj.message
    }
  }

  let message: string
  switch (status) {
    case 400:
      message = detail || 'Bad request. Please verify the uploaded file and format.'
      break
    case 404:
      message = detail || 'Requested resource or API endpoint not found on this server.'
      break
    case 413:
      message = detail || 'File exceeds server size or page limit (max 50 MB).'
      break
    case 415:
      message = detail || 'Unsupported file format or Content-Type.'
      break
    case 422:
      message = detail || 'Document could not be processed by the extraction engine.'
      break
    case 429:
      message = detail || 'Rate limit exceeded. Please wait a moment before trying again.'
      break
    case 500:
      message = detail || 'Internal pipeline processing error.'
      break
    case 503:
      message = detail || 'Service or engine temporarily unavailable. Please try again later.'
      break
    case 504:
      message = detail || 'Processing timed out. The engine took too long to complete.'
      break
    default:
      message = detail || `Request failed with HTTP status ${status}.`
  }

  return new ApiError(status, message, detail)
}
