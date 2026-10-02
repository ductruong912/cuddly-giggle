import React from 'react'
import { ImageViewer } from './ImageViewer'
import { PdfViewer } from './PdfViewer'
import { OfficeViewer } from './OfficeViewer'
import type { UploadedDocument } from '@/types/document'

interface DocumentViewerProps {
  document: UploadedDocument
}

export const DocumentViewer: React.FC<DocumentViewerProps> = ({ document }) => {
  return (
    <div className="w-full h-full flex flex-col bg-white dark:bg-zinc-950 overflow-hidden">
      {/* Source Panel Header */}
      <div className="h-10 px-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between shrink-0 bg-white dark:bg-zinc-950">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
            Source
          </span>
          <span className="text-xs text-zinc-400 dark:text-zinc-600">•</span>
          <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200 truncate max-w-[200px] sm:max-w-[280px]">
            {document.name}
          </span>
        </div>

        <span className="text-[11px] font-mono uppercase px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 font-medium">
          {document.type}
        </span>
      </div>

      {/* Viewer Content */}
      <div className="flex-1 w-full h-full overflow-hidden relative">
        {document.type === 'image' && document.previewUrl && (
          <ImageViewer url={document.previewUrl} alt={document.name} />
        )}

        {document.type === 'pdf' && document.previewUrl && (
          <PdfViewer url={document.previewUrl} name={document.name} />
        )}

        {document.type === 'office' && (
          <OfficeViewer
            name={document.name}
            extension={document.extension}
            size={document.size}
          />
        )}

        {document.type === 'markdown' && document.previewUrl && (
          <div className="w-full h-full p-6 overflow-auto font-mono text-xs text-zinc-800 dark:text-zinc-200 whitespace-pre-wrap">
            {/* Direct markdown file */}
            Preview available upon running OCR / Extraction.
          </div>
        )}
      </div>
    </div>
  )
}
