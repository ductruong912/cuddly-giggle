import React, { useState, useRef, useCallback } from 'react'

interface SplitPaneProps {
  left: React.ReactNode
  right: React.ReactNode
  initialLeftRatio?: number // default 0.45
}

export const SplitPane: React.FC<SplitPaneProps> = ({
  left,
  right,
  initialLeftRatio = 0.45,
}) => {
  const [leftRatio, setLeftRatio] = useState(initialLeftRatio)
  const isDragging = useRef(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const handleMouseMove = (event: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      const newRatio = (event.clientX - rect.left) / rect.width
      // Clamp ratio between 25% and 75%
      const clampedRatio = Math.max(0.25, Math.min(0.75, newRatio))
      setLeftRatio(clampedRatio)
    }

    const handleMouseUp = () => {
      isDragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
  }, [])

  return (
    <div
      ref={containerRef}
      className="flex-1 w-full h-full flex flex-col lg:flex-row overflow-hidden relative"
    >
      {/* Left Panel: Source Document */}
      <div
        style={{ flex: `${leftRatio * 100}%` }}
        className="w-full lg:h-full h-1/2 overflow-hidden flex flex-col min-w-[280px]"
      >
        {left}
      </div>

      {/* Subtle Divider (Desktop only) */}
      <div
        onMouseDown={handleMouseDown}
        className="hidden lg:flex w-1.5 hover:w-2 -mx-0.5 bg-zinc-200 dark:bg-zinc-800 hover:bg-blue-500/60 transition-all cursor-col-resize items-center justify-center z-10 select-none group"
      >
        <div className="w-0.5 h-8 bg-zinc-400 dark:bg-zinc-600 group-hover:bg-white rounded-full transition-colors" />
      </div>

      {/* Right Panel: Output */}
      <div
        style={{ flex: `${(1 - leftRatio) * 100}%` }}
        className="w-full lg:h-full h-1/2 overflow-hidden flex flex-col min-w-[320px] border-t lg:border-t-0 lg:border-l border-zinc-200 dark:border-zinc-800"
      >
        {right}
      </div>
    </div>
  )
}
