import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { DocumentType } from '@/types/document'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024 // 50 MB

export const SUPPORTED_EXTENSIONS = [
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
] as const

export const SUPPORTED_EXTENSIONS_STRING = SUPPORTED_EXTENSIONS.join(', ')

export function getDocumentType(filename: string): DocumentType {
  const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase()
  if (ext === '.pdf') return 'pdf'
  if (['.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'].includes(ext)) {
    return 'image'
  }
  if (['.doc', '.docx', '.xls', '.xlsx', '.xlsm'].includes(ext)) {
    return 'office'
  }
  if (['.md', '.markdown'].includes(ext)) {
    return 'markdown'
  }
  return 'unknown'
}

export function isSupportedFile(file: File): boolean {
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  return SUPPORTED_EXTENSIONS.includes(ext as (typeof SUPPORTED_EXTENSIONS)[number])
}

export function formatBytes(bytes: number, decimals = 1): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`
}

export function formatDuration(seconds: number): string {
  if (seconds < 1) {
    return `${(seconds * 1000).toFixed(0)} ms`
  }
  return `${seconds.toFixed(2)} s`
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
    const textArea = document.createElement('textarea')
    textArea.value = text
    textArea.style.position = 'fixed'
    textArea.style.left = '-999999px'
    textArea.style.top = '-999999px'
    document.body.appendChild(textArea)
    textArea.focus()
    textArea.select()
    const successful = document.execCommand('copy')
    textArea.remove()
    return successful
  } catch {
    return false
  }
}

export function downloadFile(content: string, filename: string, mimeType = 'text/plain') {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
