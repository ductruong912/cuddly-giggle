import React, { useState, lazy, Suspense } from 'react'
import { ImageViewer } from './ImageViewer'
import { OfficeViewer } from './OfficeViewer'
import type { UploadedDocument } from '@/types/document'
import type { DocumentParseResponse } from '@/types/api'
import { Loader2 } from 'lucide-react'

const PdfViewer = lazy(() => import('./PdfViewer'))
const OcrInspector = lazy(() => import('./OcrInspector'))

interface DocumentViewerProps {
  document: UploadedDocument
  parseResponse?: DocumentParseResponse
  viewMode?: 'original' | 'inspector'
  onViewModeChange?: (mode: 'original' | 'inspector') => void
  activePageIndex?: number
  selectedBlockId?: string | null
  hoveredBlockId?: string | null
  onPageChange?: (pageIndex: number) => void
  onBlockSelect?: (blockId: string | null) => void
  onBlockHover?: (blockId: string | null) => void
}

export const DocumentViewer: React.FC<DocumentViewerProps> = ({
  document,
  parseResponse,
  viewMode,
  onViewModeChange,
  activePageIndex = 0,
  selectedBlockId = null,
  hoveredBlockId = null,
  onPageChange,
  onBlockSelect,
  onBlockHover,
}) => {
  const [internalViewMode, setInternalViewMode] = useState<'original' | 'inspector'>('original')
  const currentViewMode = viewMode ?? internalViewMode

  const setViewMode = (mode: 'original' | 'inspector') => {
    setInternalViewMode(mode)
    onViewModeChange?.(mode)
  }

  const hasVisual = Boolean(
    parseResponse?.pages?.some((p) => p.visual && p.visual.available)
  )

  return (
    <div className="w-full h-full flex flex-col bg-white dark:bg-zinc-950 overflow-hidden">
      {/* Source Panel Header */}
      <div className="h-10 px-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between shrink-0 bg-white dark:bg-zinc-950 select-none">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
            Source
          </span>
          <span className="text-xs text-zinc-400 dark:text-zinc-600">•</span>
          <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200 truncate max-w-[140px] sm:max-w-[200px]">
            {document.name}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* View mode toggle: [ Original ] [ OCR Inspector ] when visual is available */}
          {hasVisual && (
            <div
              role="tablist"
              aria-label="Source view mode"
              className="inline-flex p-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-xs"
            >
              <button
                type="button"
                role="tab"
                aria-selected={currentViewMode === 'original'}
                onClick={() => setViewMode('original')}
                title="Original source"
                className={`px-2.5 py-0.5 rounded-md font-medium transition-all ${
                  currentViewMode === 'original'
                    ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                Original
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={currentViewMode === 'inspector'}
                onClick={() => setViewMode('inspector')}
                title="OCR processed view"
                className={`px-2.5 py-0.5 rounded-md font-medium transition-all ${
                  currentViewMode === 'inspector'
                    ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                OCR Inspector
              </button>
            </div>
          )}

          <span className="text-[11px] font-mono uppercase px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 font-medium">
            {document.type}
          </span>
        </div>
      </div>

      {/* Viewer Content */}
      <div className="flex-1 w-full h-full overflow-hidden relative">
        {currentViewMode === 'inspector' && hasVisual && parseResponse ? (
          <Suspense
            fallback={
              <div className="w-full h-full flex flex-col items-center justify-center p-8 bg-zinc-50/50 dark:bg-zinc-950 text-center select-none text-zinc-500">
                <Loader2 className="w-6 h-6 animate-spin text-zinc-400 mb-2" />
                <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  Loading OCR Inspector...
                </span>
              </div>
            }
          >
            <OcrInspector
              pages={parseResponse.pages}
              activePageIndex={activePageIndex}
              selectedBlockId={selectedBlockId}
              hoveredBlockId={hoveredBlockId}
              onPageChange={onPageChange ?? (() => {})}
              onBlockSelect={onBlockSelect ?? (() => {})}
              onBlockHover={onBlockHover ?? (() => {})}
            />
          </Suspense>
        ) : (
          <>
            {document.type === 'image' && document.previewUrl && (
              <ImageViewer url={document.previewUrl} alt={document.name} />
            )}

            {document.type === 'pdf' && document.previewUrl && (
              <Suspense
                fallback={
                  <div className="w-full h-full flex flex-col items-center justify-center p-8 bg-zinc-50/50 dark:bg-zinc-950 text-center select-none text-zinc-500">
                    <Loader2 className="w-6 h-6 animate-spin text-zinc-400 mb-2" />
                    <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                      Loading PDF engine...
                    </span>
                  </div>
                }
              >
                <PdfViewer
                  url={document.previewUrl}
                  name={document.name}
                  currentPage={activePageIndex + 1}
                  onPageChange={(p) => onPageChange?.(p - 1)}
                />
              </Suspense>
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
                Preview available upon running OCR / Extraction.
              </div>
            )}

            {!document.previewUrl && document.type !== 'office' && (
              <div className="w-full h-full p-8 flex flex-col items-center justify-center text-center text-zinc-400 bg-zinc-50/30 dark:bg-zinc-950">
                <div className="max-w-xs space-y-2">
                  <span className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
                    Historical record loaded
                  </span>
                  <p className="text-[11px] text-zinc-500">
                    Viewing extracted data for{' '}
                    <span className="font-mono text-zinc-700 dark:text-zinc-300">
                      {document.name}
                    </span>
                    . Original document file is stored on the server.
                  </p>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default DocumentViewer
