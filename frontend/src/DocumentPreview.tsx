import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, FileText, LoaderCircle, Minus, Plus } from 'lucide-react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import { fileSuffix } from './api'

function ZoomControls({ zoom, onChange }: { zoom: number; onChange: (value: number) => void }) {
  return (
    <div className="zoom-controls">
      <button
        className="icon-button"
        aria-label="Thu nhỏ"
        disabled={zoom <= 0.5}
        onClick={() => onChange(Math.max(0.5, zoom - 0.25))}
      >
        <Minus size={15} />
      </button>
      <span>{Math.round(zoom * 100)}%</span>
      <button
        className="icon-button"
        aria-label="Phóng to"
        disabled={zoom >= 2}
        onClick={() => onChange(Math.min(2, zoom + 0.25))}
      >
        <Plus size={15} />
      </button>
    </div>
  )
}

function PDFPreview({ file }: { file: File }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const container = useRef<HTMLDivElement>(null)
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [width, setWidth] = useState(600)
  const [error, setError] = useState('')
  const [rendering, setRendering] = useState(true)

  useEffect(() => {
    const element = container.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(160, entry.contentRect.width)),
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let disposed = false
    let loading: ReturnType<(typeof import('pdfjs-dist'))['getDocument']> | undefined
    async function load() {
      try {
        const pdfjs = await import('pdfjs-dist')
        const worker = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
        if (disposed) return
        pdfjs.GlobalWorkerOptions.workerSrc = worker
        const bytes = await file.arrayBuffer()
        if (disposed) return
        loading = pdfjs.getDocument({
          data: bytes,
          enableXfa: false,
          cMapUrl: '/assets/pdfjs/cmaps/',
          standardFontDataUrl: '/assets/pdfjs/standard_fonts/',
          wasmUrl: '/assets/pdfjs/wasm/',
        })
        const pdf = await loading.promise
        if (!disposed) setDocument(pdf)
      } catch {
        if (!disposed) setError('Không xem trước được PDF này. Bạn vẫn có thể gửi file để đọc/OCR.')
      }
    }
    void load()
    return () => {
      disposed = true
      void loading?.destroy()
    }
  }, [file])

  useEffect(() => {
    if (!document || !canvas.current) return
    let disposed = false
    let task: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined
    const target = canvas.current
    async function render() {
      setRendering(true)
      try {
        const pdfPage = await document!.getPage(page)
        if (disposed) return
        const original = pdfPage.getViewport({ scale: 1 })
        const viewport = pdfPage.getViewport({ scale: (width / original.width) * zoom })
        const ratio = Math.min(window.devicePixelRatio || 1, 2)
        target.width = Math.ceil(viewport.width * ratio)
        target.height = Math.ceil(viewport.height * ratio)
        target.style.width = `${viewport.width}px`
        target.style.height = `${viewport.height}px`
        task = pdfPage.render({
          canvas: target,
          viewport,
          transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
        })
        await task.promise
      } catch (cause) {
        if (
          !disposed &&
          !(cause instanceof Error && cause.name === 'RenderingCancelledException')
        ) {
          setError('Không dựng được trang PDF. Bạn vẫn có thể chạy OCR cho file này.')
        }
      } finally {
        if (!disposed) setRendering(false)
      }
    }
    void render()
    return () => {
      disposed = true
      task?.cancel()
    }
  }, [document, page, width, zoom])

  return (
    <div className="document-preview pdf-preview">
      <div className="preview-toolbar">
        <div className="page-controls">
          <button
            className="icon-button"
            aria-label="Trang trước"
            disabled={!document || page === 1}
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft size={16} />
          </button>
          <span aria-live="polite">
            {document ? `Trang ${page} / ${document.numPages}` : 'PDF'}
          </span>
          <button
            className="icon-button"
            aria-label="Trang sau"
            disabled={!document || page === document.numPages}
            onClick={() => setPage(page + 1)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
        <ZoomControls zoom={zoom} onChange={setZoom} />
      </div>
      <div className="preview-scroll" ref={container}>
        {error ? (
          <div className="preview-notice" role="status">
            <FileText size={30} />
            <p>{error}</p>
          </div>
        ) : (
          <>
            {rendering && (
              <span className="preview-loading" role="status">
                <LoaderCircle className="spin" size={16} /> Đang dựng trang…
              </span>
            )}
            <canvas ref={canvas} className="pdf-canvas" aria-label={`Bản gốc PDF, trang ${page}`} />
          </>
        )}
      </div>
    </div>
  )
}

function ImagePreview({ file, url }: { file: File; url: string }) {
  const [zoom, setZoom] = useState(1)
  const [failed, setFailed] = useState(false)
  return (
    <div className="document-preview">
      <div className="preview-toolbar">
        <span>Ảnh gốc</span>
        <ZoomControls zoom={zoom} onChange={setZoom} />
      </div>
      <div className="preview-scroll image-scroll">
        {failed ? (
          <p className="preview-notice">Không xem trước được ảnh này. Bạn vẫn có thể chạy OCR.</p>
        ) : (
          <img
            src={url}
            alt={`Bản gốc ${file.name}`}
            className="image-preview"
            style={{ width: `${zoom * 100}%`, maxWidth: 'none' }}
            onError={() => setFailed(true)}
          />
        )}
      </div>
    </div>
  )
}

export default function DocumentPreview({ file, url }: { file: File; url: string }) {
  const suffix = fileSuffix(file.name)
  if (suffix === '.pdf') return <PDFPreview file={file} />
  if (['.png', '.jpg', '.jpeg', '.bmp', '.webp'].includes(suffix))
    return <ImagePreview file={file} url={url} />
  return (
    <div className="file-fallback">
      <div className="file-sheet">
        <FileText size={42} strokeWidth={1.2} />
        <span>{suffix.slice(1).toUpperCase()}</span>
      </div>
      <p className="fallback-description">Chưa hỗ trợ xem trước định dạng này.</p>
    </div>
  )
}
