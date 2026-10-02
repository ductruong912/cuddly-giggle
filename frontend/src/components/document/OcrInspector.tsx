import React, { useState } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Loader2,
  AlertTriangle,
} from 'lucide-react'
import type { ParseBlock, ParsePage } from '@/types/api'

interface OcrInspectorProps {
  pages: ParsePage[]
  activePageIndex: number
  selectedBlockId: string | null
  hoveredBlockId: string | null
  onPageChange: (index: number) => void
  onBlockSelect: (blockId: string | null) => void
  onBlockHover: (blockId: string | null) => void
}

export const OcrInspector: React.FC<OcrInspectorProps> = ({
  pages,
  activePageIndex,
  selectedBlockId,
  hoveredBlockId,
  onPageChange,
  onBlockSelect,
  onBlockHover,
}) => {
  const [scale, setScale] = useState<number>(1.0)
  const [imageLoading, setImageLoading] = useState<boolean>(true)
  const [imageError, setImageError] = useState<boolean>(false)

  const numPages = pages.length
  const currentPage = pages[activePageIndex] || pages[0]

  // Reset image loading states when active page changes
  const prevPageUrlRef = React.useRef<string | null>(null)
  const currentUrl = currentPage?.visual?.url || null

  if (currentUrl !== prevPageUrlRef.current) {
    prevPageUrlRef.current = currentUrl
    setImageLoading(true)
    setImageError(false)
  }

  const handlePrevPage = () => {
    if (activePageIndex > 0) {
      onPageChange(activePageIndex - 1)
    }
  }

  const handleNextPage = () => {
    if (activePageIndex < numPages - 1) {
      onPageChange(activePageIndex + 1)
    }
  }

  const zoomIn = () => setScale((s) => Math.min(s + 0.2, 3.0))
  const zoomOut = () => setScale((s) => Math.max(s - 0.2, 0.5))
  const resetZoom = () => setScale(1.0)

  if (!currentPage) {
    return (
      <div className="w-full h-full flex items-center justify-center p-8 text-center text-zinc-500">
        <span className="text-xs">No parsed pages available.</span>
      </div>
    )
  }

  const geometry = currentPage.geometry
  const hasValidGeometry =
    geometry && geometry.width > 0 && geometry.height > 0

  const getBlockPolygonStyle = (block: ParseBlock) => {
    const isSelected = block.block_id === selectedBlockId
    const isHovered = block.block_id === hoveredBlockId

    if (isSelected) {
      return {
        stroke: '#f59e0b', // amber-500
        strokeWidth: 2.5,
        fill: 'rgba(245, 158, 11, 0.22)',
      }
    }

    if (isHovered) {
      return {
        stroke: '#3b82f6', // blue-500
        strokeWidth: 2,
        fill: 'rgba(59, 130, 246, 0.20)',
      }
    }

    // Default style with subtle distinction by block type
    if (block.type === 'title') {
      return {
        stroke: 'rgba(99, 102, 241, 0.45)', // indigo
        strokeWidth: 1.2,
        fill: 'rgba(99, 102, 241, 0.05)',
      }
    }
    if (block.type === 'table') {
      return {
        stroke: 'rgba(168, 85, 247, 0.45)', // purple
        strokeWidth: 1.2,
        fill: 'rgba(168, 85, 247, 0.05)',
      }
    }

    return {
      stroke: 'rgba(14, 165, 233, 0.35)', // sky
      strokeWidth: 1,
      fill: 'rgba(14, 165, 233, 0.03)',
    }
  }

  return (
    <div className="relative w-full h-full flex flex-col bg-zinc-100 dark:bg-zinc-950 overflow-hidden select-none">
      {/* Floating Toolbar: Page Nav & Zoom Controls */}
      <div className="absolute top-3 inset-x-3 z-10 flex items-center justify-between pointer-events-none">
        {/* Page Nav */}
        <div className="pointer-events-auto flex items-center gap-1 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-xs border border-zinc-200 dark:border-zinc-800 rounded-lg p-1 shadow-xs">
          <button
            type="button"
            onClick={handlePrevPage}
            disabled={activePageIndex <= 0}
            className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 disabled:opacity-30 disabled:pointer-events-none transition-colors"
            title="Previous page"
            aria-label="Previous page"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-xs font-mono font-medium px-2 text-zinc-700 dark:text-zinc-300">
            {activePageIndex + 1} / {numPages}
          </span>
          <button
            type="button"
            onClick={handleNextPage}
            disabled={activePageIndex >= numPages - 1}
            className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 disabled:opacity-30 disabled:pointer-events-none transition-colors"
            title="Next page"
            aria-label="Next page"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        {/* Zoom Controls */}
        <div className="pointer-events-auto flex items-center gap-1 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-xs border border-zinc-200 dark:border-zinc-800 rounded-lg p-1 shadow-xs">
          <button
            type="button"
            onClick={zoomOut}
            className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 transition-colors"
            title="Zoom out"
            aria-label="Zoom out"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-[11px] font-mono font-medium px-1 text-zinc-600 dark:text-zinc-400 min-w-10 text-center">
            {Math.round(scale * 100)}%
          </span>
          <button
            type="button"
            onClick={zoomIn}
            className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 transition-colors"
            title="Zoom in"
            aria-label="Zoom in"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <div className="w-[1px] h-3.5 bg-zinc-200 dark:bg-zinc-800 my-auto mx-0.5" />
          <button
            type="button"
            onClick={resetZoom}
            className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 transition-colors"
            title="Reset zoom"
            aria-label="Reset zoom"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Main Viewport */}
      <div className="flex-1 w-full h-full overflow-auto pt-16 pb-8 px-4 flex items-center justify-center">
        {/* Loading Spinner */}
        {imageLoading && !imageError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-zinc-500 z-0">
            <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
            <span className="text-xs">Loading page visualization...</span>
          </div>
        )}

        {/* Error / Expired artifact UI */}
        {imageError ? (
          <div className="max-w-md p-6 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-sm text-center space-y-3">
            <div className="w-10 h-10 mx-auto rounded-full bg-amber-50 dark:bg-amber-950/50 border border-amber-200 dark:border-amber-800 flex items-center justify-center text-amber-600 dark:text-amber-400">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div>
              <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                OCR visualization is no longer available.
              </h4>
              <p className="text-xs text-zinc-500 mt-1.5">
                Re-run OCR to regenerate the page visualization.
              </p>
            </div>
          </div>
        ) : (
          <div
            className="relative transition-transform duration-100 shadow-md rounded border border-zinc-300/80 dark:border-zinc-800 bg-white"
            style={{
              transform: `scale(${scale})`,
              transformOrigin: 'top center',
            }}
          >
            {currentPage.visual.url && (
              <img
                src={currentPage.visual.url}
                alt={`OCR processed page ${activePageIndex + 1}`}
                className="block max-w-full h-auto select-none pointer-events-none"
                onLoad={() => setImageLoading(false)}
                onError={() => {
                  setImageLoading(false)
                  setImageError(true)
                }}
              />
            )}

            {/* SVG Bounding Boxes Overlay */}
            {!imageLoading && !imageError && hasValidGeometry && (
              <svg
                data-testid="ocr-inspector-svg"
                className="absolute inset-0 w-full h-full pointer-events-none"
                viewBox={`0 0 ${geometry.width} ${geometry.height}`}
                preserveAspectRatio="xMidYMid meet"
              >
                {currentPage.blocks.map((block) => {
                  // Rule 6: Only draw block if bbox exists and has >= 3 points
                  if (!block.bbox || block.bbox.length < 3) {
                    return null
                  }

                  const pointsString = block.bbox
                    .map((pt) => `${pt.x},${pt.y}`)
                    .join(' ')
                  const style = getBlockPolygonStyle(block)

                  return (
                    <polygon
                      key={block.block_id}
                      data-block-id={block.block_id}
                      points={pointsString}
                      fill={style.fill}
                      stroke={style.stroke}
                      strokeWidth={style.strokeWidth}
                      className="cursor-pointer pointer-events-auto transition-all duration-150"
                      onClick={() => onBlockSelect(block.block_id)}
                      onMouseEnter={() => onBlockHover(block.block_id)}
                      onMouseLeave={() => onBlockHover(null)}
                    >
                      <title>{`${block.type.toUpperCase()}: ${block.content.slice(0, 80)}`}</title>
                    </polygon>
                  )
                })}
              </svg>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default OcrInspector
