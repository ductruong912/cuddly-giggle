import React, { useEffect, useRef } from 'react'
import type { ParseBlock } from '@/types/api'

interface BlocksViewProps {
  blocks: ParseBlock[]
  readingOrder?: string[]
  selectedBlockId: string | null
  hoveredBlockId: string | null
  onBlockSelect: (blockId: string | null) => void
  onBlockHover: (blockId: string | null) => void
}

export const BlocksView: React.FC<BlocksViewProps> = ({
  blocks,
  readingOrder = [],
  selectedBlockId,
  hoveredBlockId,
  onBlockSelect,
  onBlockHover,
}) => {
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  // Sort blocks by reading_order if available; fallback to original array order
  const sortedBlocks = React.useMemo(() => {
    if (!readingOrder || readingOrder.length === 0) {
      return blocks
    }

    const blockMap = new Map<string, ParseBlock>()
    for (const b of blocks) {
      blockMap.set(b.block_id, b)
    }

    const ordered: ParseBlock[] = []
    const seen = new Set<string>()

    for (const id of readingOrder) {
      const b = blockMap.get(id)
      if (b) {
        ordered.push(b)
        seen.add(id)
      }
    }

    // Append any blocks not listed in reading_order to ensure nothing is lost
    for (const b of blocks) {
      if (!seen.has(b.block_id)) {
        ordered.push(b)
      }
    }

    return ordered
  }, [blocks, readingOrder])

  // Scroll selected block into view smoothly
  useEffect(() => {
    if (selectedBlockId) {
      const el = cardRefs.current.get(selectedBlockId)
      if (el) {
        el.scrollIntoView({
          block: 'nearest',
          behavior: 'smooth',
        })
      }
    }
  }, [selectedBlockId])

  if (sortedBlocks.length === 0) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center p-8 text-center text-zinc-400">
        <span className="text-xs">No blocks found on this page.</span>
      </div>
    )
  }

  const renderConfidenceBadge = (block: ParseBlock) => {
    if (block.confidence_source === 'real_engine') {
      const pct = Math.round(block.confidence * 100)
      return (
        <span
          data-testid="confidence-badge"
          className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/80 font-medium"
        >
          {pct}%
        </span>
      )
    }

    if (block.confidence_source === 'synthesized') {
      return (
        <span
          data-testid="confidence-badge"
          className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-zinc-700 font-medium"
        >
          Derived
        </span>
      )
    }

    // confidence_source === 'unknown': do not display fake confidence
    return null
  }

  const getTypeBadgeStyle = (type: string) => {
    switch (type) {
      case 'title':
        return 'bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-900'
      case 'table':
        return 'bg-purple-50 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-900'
      case 'header':
      case 'footer':
        return 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border-zinc-200 dark:border-zinc-700'
      default:
        return 'bg-sky-50 dark:bg-sky-950/60 text-sky-700 dark:text-sky-300 border-sky-200 dark:border-sky-900'
    }
  }

  return (
    <div
      role="region"
      aria-label="Document blocks list"
      className="w-full h-full overflow-y-auto p-4 space-y-2.5 bg-zinc-50/30 dark:bg-zinc-950"
    >
      <div className="flex items-center justify-between text-xs text-zinc-500 mb-2 px-1">
        <span className="font-medium">
          {sortedBlocks.length} {sortedBlocks.length === 1 ? 'block' : 'blocks'}
        </span>
        <span className="text-[11px] font-mono text-zinc-400">
          Reading order
        </span>
      </div>

      {sortedBlocks.map((block) => {
        const isSelected = block.block_id === selectedBlockId
        const isHovered = block.block_id === hoveredBlockId

        return (
          <div
            key={block.block_id}
            ref={(el) => {
              if (el) cardRefs.current.set(block.block_id, el)
              else cardRefs.current.delete(block.block_id)
            }}
            role="button"
            tabIndex={0}
            aria-selected={isSelected}
            onClick={() =>
              onBlockSelect(isSelected ? null : block.block_id)
            }
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onBlockSelect(isSelected ? null : block.block_id)
              }
            }}
            onMouseEnter={() => onBlockHover(block.block_id)}
            onMouseLeave={() => onBlockHover(null)}
            className={`w-full text-left p-3 rounded-lg border transition-all cursor-pointer select-none focus:outline-hidden focus:ring-2 focus:ring-blue-500/50 ${
              isSelected
                ? 'bg-amber-50/70 dark:bg-amber-950/30 border-amber-400 dark:border-amber-600 shadow-xs'
                : isHovered
                ? 'bg-blue-50/50 dark:bg-blue-950/20 border-blue-300 dark:border-blue-700 shadow-2xs'
                : 'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-700'
            }`}
          >
            {/* Header: Type Badge, ID, & Confidence */}
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <div className="flex items-center gap-1.5">
                <span
                  className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded border font-semibold ${getTypeBadgeStyle(
                    block.type
                  )}`}
                >
                  {block.type}
                </span>
                <span className="text-[10px] font-mono text-zinc-400 truncate max-w-[120px]">
                  {block.block_id}
                </span>
              </div>

              {renderConfidenceBadge(block)}
            </div>

            {/* Content Preview (Plain text, line-clamp-3) */}
            <p className="text-xs text-zinc-800 dark:text-zinc-200 leading-relaxed font-sans line-clamp-3 whitespace-pre-wrap break-words">
              {block.content || <span className="italic text-zinc-400">Empty content</span>}
            </p>
          </div>
        )
      })}
    </div>
  )
}

export default BlocksView
