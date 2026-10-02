import { useCallback, useEffect, useState } from 'react'
import type { UploadedDocument } from '@/types/document'
import {
  MAX_UPLOAD_BYTES,
  SUPPORTED_EXTENSIONS_STRING,
  formatBytes,
  getDocumentType,
  isSupportedFile,
} from '@/lib/utils'

export function useDocument() {
  const [document, setDocument] = useState<UploadedDocument | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isDragActive, setIsDragActive] = useState(false)

  const selectFile = useCallback((file: File) => {
    setError(null)

    if (!isSupportedFile(file)) {
      setError(`Unsupported file type. Please upload one of: ${SUPPORTED_EXTENSIONS_STRING}`)
      return false
    }

    if (file.size > MAX_UPLOAD_BYTES) {
      setError(
        `File is too large (${formatBytes(file.size)}). Maximum upload size is ${formatBytes(MAX_UPLOAD_BYTES)}.`
      )
      return false
    }

    const type = getDocumentType(file.name)
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()

    let previewUrl: string | undefined
    if (type === 'image' || type === 'pdf') {
      previewUrl = URL.createObjectURL(file)
    }

    setDocument((prev) => {
      if (prev?.previewUrl) {
        URL.revokeObjectURL(prev.previewUrl)
      }
      return {
        file,
        name: file.name,
        size: file.size,
        type,
        extension: ext,
        previewUrl,
      }
    })

    return true
  }, [])

  const clearDocument = useCallback(() => {
    setDocument((prev) => {
      if (prev?.previewUrl) {
        URL.revokeObjectURL(prev.previewUrl)
      }
      return null
    })
    setError(null)
  }, [])

  useEffect(() => {
    return () => {
      if (document?.previewUrl) {
        URL.revokeObjectURL(document.previewUrl)
      }
    }
  }, [document])

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragActive(true)
  }, [])

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragActive(false)
  }, [])

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragActive(false)

      const files = e.dataTransfer.files
      if (files && files.length > 0) {
        selectFile(files[0])
      }
    },
    [selectFile]
  )

  return {
    document,
    error,
    isDragActive,
    selectFile,
    clearDocument,
    setError,
    onDragOver,
    onDragLeave,
    onDrop,
  }
}
