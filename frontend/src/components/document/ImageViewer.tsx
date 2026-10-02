import React, { useState, useRef } from 'react'
import { ZoomIn, ZoomOut, RotateCcw } from 'lucide-react'

interface ImageViewerProps {
  url: string
  alt: string
}

export const ImageViewer: React.FC<ImageViewerProps> = ({ url, alt }) => {
  const [scale, setScale] = useState(1)
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const startPos = useRef({ x: 0, y: 0 })

  const zoomIn = () => setScale((s) => Math.min(s + 0.25, 4))
  const zoomOut = () => setScale((s) => Math.max(s - 0.25, 0.5))
  const resetZoom = () => {
    setScale(1)
    setPosition({ x: 0, y: 0 })
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    if (scale <= 1) return
    setIsPanning(true)
    startPos.current = { x: e.clientX - position.x, y: e.clientY - position.y }
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isPanning) return
    setPosition({
      x: e.clientX - startPos.current.x,
      y: e.clientY - startPos.current.y,
    })
  }

  const handleMouseUp = () => {
    setIsPanning(false)
  }

  return (
    <div className="relative w-full h-full flex flex-col bg-zinc-100 dark:bg-zinc-950 overflow-hidden select-none">
      {/* Floating Image Controls */}
      <div className="absolute top-3 right-3 z-10 flex items-center gap-1 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-xs border border-zinc-200 dark:border-zinc-800 rounded-lg p-1 shadow-xs">
        <button
          type="button"
          onClick={zoomOut}
          className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 transition-colors"
          title="Zoom out"
        >
          <ZoomOut className="w-3.5 h-3.5" />
        </button>
        <span className="text-[11px] font-mono font-medium px-1.5 text-zinc-600 dark:text-zinc-400 min-w-10 text-center">
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
          onClick={resetZoom}
          className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 transition-colors"
          title="Reset zoom & position"
        >
          <RotateCcw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Image Canvas Container */}
      <div
        className={`flex-1 w-full h-full flex items-center justify-center p-4 overflow-hidden ${
          scale > 1 ? 'cursor-grab active:cursor-grabbing' : 'cursor-default'
        }`}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <img
          src={url}
          alt={alt}
          draggable={false}
          style={{
            transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
            transition: isPanning ? 'none' : 'transform 0.15s ease-out',
          }}
          className="max-w-full max-h-full object-contain rounded shadow-xs"
        />
      </div>
    </div>
  )
}
