import React, { useEffect, useRef, useState, useCallback } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import {
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Maximize2,
  RotateCcw,
  Loader2,
} from 'lucide-react'

// Configure PDF.js worker
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url
).toString()

interface PdfViewerProps {
  url: string
  name: string
  currentPage?: number
  onPageChange?: (page: number) => void
}

export const PdfViewer: React.FC<PdfViewerProps> = ({
  url,
  name,
  currentPage: externalPage,
  onPageChange,
}) => {
  const [numPages, setNumPages] = useState<number>(1)
  const [internalPage, setInternalPage] = useState<number>(1)
  const [scale, setScale] = useState<number>(1.2)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const currentPage =
    externalPage !== undefined && externalPage >= 1 && externalPage <= numPages
      ? externalPage
      : internalPage

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const pdfDocRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null)
  const renderTaskRef = useRef<pdfjsLib.RenderTask | null>(null)

  // Load PDF Document
  useEffect(() => {
    let isCancelled = false

    const loadingTask = pdfjsLib.getDocument({ url })
    loadingTask.promise
      .then((pdf) => {
        if (isCancelled) return
        pdfDocRef.current = pdf
        setNumPages(pdf.numPages)
        setInternalPage(1)
        setLoading(false)
        setError(null)
      })
      .catch((err) => {
        if (isCancelled) return
        console.error('Error loading PDF:', err)
        setError('Failed to load PDF in canvas viewer.')
        setLoading(false)
      })

    return () => {
      isCancelled = true
      loadingTask.destroy()
    }
  }, [url])

  // Render current page
  const renderPage = useCallback(
    async (pageNum: number, currentScale: number) => {
      if (!pdfDocRef.current || !canvasRef.current) return

      try {
        if (renderTaskRef.current) {
          renderTaskRef.current.cancel()
        }

        const page = await pdfDocRef.current.getPage(pageNum)
        const viewport = page.getViewport({ scale: currentScale })

        const canvas = canvasRef.current
        if (!canvas) return
        const context = canvas.getContext ? canvas.getContext('2d') : null
        if (!context) return

        const dpr = window.devicePixelRatio || 1
        canvas.width = Math.floor(viewport.width * dpr)
        canvas.height = Math.floor(viewport.height * dpr)
        canvas.style.width = `${Math.floor(viewport.width)}px`
        canvas.style.height = `${Math.floor(viewport.height)}px`

        const transform = dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined

        const renderContext = {
          canvasContext: context,
          viewport: viewport,
          canvas: canvas,
          transform: transform,
        }

        const task = page.render(renderContext)
        renderTaskRef.current = task
        await task.promise
      } catch (err: unknown) {
        if (
          err &&
          typeof err === 'object' &&
          'name' in err &&
          (err as { name: string }).name === 'RenderingCancelledException'
        ) {
          // Normal when user changes page rapidly
          return
        }
        console.error('Error rendering page:', err)
      }
    },
    []
  )

  useEffect(() => {
    if (!loading && pdfDocRef.current) {
      renderPage(currentPage, scale)
    }
  }, [currentPage, scale, loading, renderPage])

  const prevPage = () => {
    const next = Math.max(currentPage - 1, 1)
    setInternalPage(next)
    onPageChange?.(next)
  }

  const nextPage = () => {
    const next = Math.min(currentPage + 1, numPages)
    setInternalPage(next)
    onPageChange?.(next)
  }

  const zoomIn = () => {
    setScale((s) => Math.min(s + 0.2, 3.0))
  }

  const zoomOut = () => {
    setScale((s) => Math.max(s - 0.2, 0.5))
  }

  const fitWidth = async () => {
    if (!pdfDocRef.current || !containerRef.current) return
    try {
      const page = await pdfDocRef.current.getPage(currentPage)
      const containerWidth = containerRef.current.clientWidth - 48
      const unscaledViewport = page.getViewport({ scale: 1.0 })
      const newScale = containerWidth / unscaledViewport.width
      setScale(Math.max(0.5, Math.min(newScale, 2.5)))
    } catch (e) {
      console.error(e)
    }
  }

  const resetZoom = () => {
    setScale(1.2)
  }

  return (
    <div className="relative w-full h-full flex flex-col bg-zinc-100 dark:bg-zinc-950 overflow-hidden select-none">
      {/* Floating PDF Controls Toolbar */}
      <div className="absolute top-3 inset-x-3 z-10 flex items-center justify-between pointer-events-none">
        {/* Page Nav */}
        <div className="pointer-events-auto flex items-center gap-1 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-xs border border-zinc-200 dark:border-zinc-800 rounded-lg p-1 shadow-xs">
          <button
            type="button"
            onClick={prevPage}
            disabled={currentPage <= 1}
            className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 disabled:opacity-30 disabled:pointer-events-none transition-colors"
            title="Previous page"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-xs font-mono font-medium px-2 text-zinc-700 dark:text-zinc-300">
            {currentPage} / {numPages}
          </span>
          <button
            type="button"
            onClick={nextPage}
            disabled={currentPage >= numPages}
            className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 disabled:opacity-30 disabled:pointer-events-none transition-colors"
            title="Next page"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        {/* Zoom & Fit controls */}
        <div className="pointer-events-auto flex items-center gap-1 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-xs border border-zinc-200 dark:border-zinc-800 rounded-lg p-1 shadow-xs">
          <button
            type="button"
            onClick={zoomOut}
            className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 transition-colors"
            title="Zoom out"
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
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <div className="w-[1px] h-3.5 bg-zinc-200 dark:bg-zinc-800 my-auto mx-0.5" />
          <button
            type="button"
            onClick={fitWidth}
            className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 transition-colors"
            title="Fit width"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={resetZoom}
            className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 transition-colors"
            title="Reset zoom"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* PDF Viewport Scroll Area */}
      <div
        ref={containerRef}
        className="flex-1 w-full h-full overflow-auto pt-16 pb-8 px-4 flex items-center justify-center"
      >
        {loading && (
          <div className="flex flex-col items-center gap-2 text-zinc-500">
            <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
            <span className="text-xs">Loading PDF document...</span>
          </div>
        )}

        {error ? (
          <div className="w-full h-full flex flex-col items-center justify-center p-4">
            <p className="text-xs text-rose-600 mb-2">{error}</p>
            <object
              data={url}
              type="application/pdf"
              title={name}
              className="w-full h-full border border-zinc-200 dark:border-zinc-800 rounded"
            >
              <p className="text-xs text-zinc-500">
                Browser preview unavailable. Click{' '}
                <a href={url} target="_blank" rel="noreferrer" className="text-blue-500 underline">
                  here to open PDF
                </a>.
              </p>
            </object>
          </div>
        ) : (
          <div className="flex justify-center transition-all">
            <canvas
              ref={canvasRef}
              className="shadow-md rounded border border-zinc-300/80 dark:border-zinc-800 bg-white"
            />
          </div>
        )}
      </div>
    </div>
  )
}

export default PdfViewer
