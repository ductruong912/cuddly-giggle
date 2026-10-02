import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import {
  Search,
  X,
  Copy,
  Check,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Info,
} from 'lucide-react'
import {
  OCR_REVIEW_LOW_CONFIDENCE_THRESHOLD,
  isReviewIssue,
} from '@/types/api'
import type { ParseBlock, ParsePage } from '@/types/api'

interface BlocksViewProps {
  blocks: ParseBlock[]
  readingOrder?: string[]
  selectedBlockId: string | null
  hoveredBlockId: string | null
  onBlockSelect: (blockId: string | null) => void
  onBlockHover: (blockId: string | null) => void
  // Phase 2C: Cross-page Review Mode props
  allPages?: ParsePage[]
  activePageIndex?: number
  onNavigateIssue?: (pageIndex: number, blockId: string) => void
}

export const BlocksView: React.FC<BlocksViewProps> = ({
  blocks,
  readingOrder = [],
  selectedBlockId,
  hoveredBlockId,
  onBlockSelect,
  onBlockHover,
  allPages,
  activePageIndex = 0,
  onNavigateIssue,
}) => {
  const cardRefs = useRef<Map<string, HTMLElement>>(new Map())
  const [searchTerm, setSearchTerm] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [confidenceFilter, setConfidenceFilter] = useState<string>('all')
  const [copied, setCopied] = useState(false)

  // 1. Sort blocks by reading_order if available; fallback to original array order
  const sortedPageBlocks = useMemo(() => {
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

    for (const b of blocks) {
      if (!seen.has(b.block_id)) {
        ordered.push(b)
      }
    }

    return ordered
  }, [blocks, readingOrder])

  // 2. Summary stats for the active page
  const pageStats = useMemo(() => {
    let lowCount = 0
    let unknownCount = 0
    let derivedCount = 0
    let realCount = 0

    for (const b of sortedPageBlocks) {
      if (b.confidence_source === 'real_engine') {
        realCount++
        if (b.confidence < OCR_REVIEW_LOW_CONFIDENCE_THRESHOLD) {
          lowCount++
        }
      } else if (b.confidence_source === 'unknown') {
        unknownCount++
      } else if (b.confidence_source === 'synthesized') {
        derivedCount++
      }
    }

    return {
      total: sortedPageBlocks.length,
      real: realCount,
      low: lowCount,
      unknown: unknownCount,
      derived: derivedCount,
    }
  }, [sortedPageBlocks])

  // 3. Filter blocks based on search, type, and confidence review filters
  const visibleBlocks = useMemo(() => {
    const term = searchTerm.toLowerCase().trim()

    return sortedPageBlocks.filter((block) => {
      // Search filter (Unicode Vietnamese case-insensitive)
      if (term) {
        const text = block.content.toLowerCase()
        if (!text.includes(term)) {
          return false
        }
      }

      // Type filter
      if (typeFilter !== 'all' && block.type !== typeFilter) {
        return false
      }

      // Confidence review filter
      if (confidenceFilter === 'low') {
        if (
          block.confidence_source !== 'real_engine' ||
          block.confidence >= OCR_REVIEW_LOW_CONFIDENCE_THRESHOLD
        ) {
          return false
        }
      } else if (confidenceFilter === 'unknown') {
        if (block.confidence_source !== 'unknown') {
          return false
        }
      } else if (confidenceFilter === 'derived') {
        if (block.confidence_source !== 'synthesized') {
          return false
        }
      }

      return true
    })
  }, [sortedPageBlocks, searchTerm, typeFilter, confidenceFilter])

  // 4. Document-wide issues for cross-page navigation
  const documentIssues = useMemo(() => {
    const list: Array<{ block: ParseBlock; pageIndex: number }> = []

    if (allPages && allPages.length > 0) {
      allPages.forEach((p, pIdx) => {
        p.blocks.forEach((b) => {
          if (isReviewIssue(b.confidence, b.confidence_source)) {
            list.push({ block: b, pageIndex: pIdx })
          }
        })
      })
    } else {
      // Fallback to active page if allPages not provided
      blocks.forEach((b) => {
        if (isReviewIssue(b.confidence, b.confidence_source)) {
          list.push({ block: b, pageIndex: activePageIndex })
        }
      })
    }

    return list
  }, [allPages, blocks, activePageIndex])

  // Find index of currently selected block in documentIssues
  const currentIssueIndex = useMemo(() => {
    if (!selectedBlockId || documentIssues.length === 0) return -1
    return documentIssues.findIndex((item) => item.block.block_id === selectedBlockId)
  }, [selectedBlockId, documentIssues])

  // Navigate to an issue
  const goToIssue = useCallback(
    (index: number) => {
      if (index < 0 || index >= documentIssues.length) return
      const target = documentIssues[index]
      if (onNavigateIssue) {
        onNavigateIssue(target.pageIndex, target.block.block_id)
      } else {
        onBlockSelect(target.block.block_id)
      }
    },
    [documentIssues, onNavigateIssue, onBlockSelect]
  )

  const handlePrevIssue = useCallback(() => {
    if (documentIssues.length === 0) return
    if (currentIssueIndex > 0) {
      goToIssue(currentIssueIndex - 1)
    } else if (currentIssueIndex === -1) {
      goToIssue(0)
    }
  }, [documentIssues.length, currentIssueIndex, goToIssue])

  const handleNextIssue = useCallback(() => {
    if (documentIssues.length === 0) return
    if (currentIssueIndex < documentIssues.length - 1) {
      goToIssue(currentIssueIndex + 1)
    } else if (currentIssueIndex === -1) {
      goToIssue(0)
    }
  }, [documentIssues.length, currentIssueIndex, goToIssue])

  // 5. Selected block detail object
  const selectedBlock = useMemo(() => {
    if (!selectedBlockId) return null
    // First search in active page blocks
    const foundOnPage = blocks.find((b) => b.block_id === selectedBlockId)
    if (foundOnPage) return foundOnPage

    // Search across allPages if available
    if (allPages) {
      for (const p of allPages) {
        const found = p.blocks.find((b) => b.block_id === selectedBlockId)
        if (found) return found
      }
    }
    return null
  }, [selectedBlockId, blocks, allPages])

  // Handle Copy text
  const handleCopyText = useCallback(() => {
    if (!selectedBlock) return
    navigator.clipboard.writeText(selectedBlock.content || '')
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }, [selectedBlock])

  // 6. Smooth scroll selected block into view
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

  // 7. Keyboard review workflow
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Do not trigger shortcuts if user is typing in an input, textarea or select
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select') {
        return
      }

      if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault()
        if (visibleBlocks.length === 0) return
        const currentIndex = visibleBlocks.findIndex((b) => b.block_id === selectedBlockId)
        if (currentIndex === -1 || currentIndex >= visibleBlocks.length - 1) {
          onBlockSelect(visibleBlocks[0].block_id)
        } else {
          onBlockSelect(visibleBlocks[currentIndex + 1].block_id)
        }
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault()
        if (visibleBlocks.length === 0) return
        const currentIndex = visibleBlocks.findIndex((b) => b.block_id === selectedBlockId)
        if (currentIndex <= 0) {
          onBlockSelect(visibleBlocks[visibleBlocks.length - 1].block_id)
        } else {
          onBlockSelect(visibleBlocks[currentIndex - 1].block_id)
        }
      } else if (e.key.toLowerCase() === 'n') {
        e.preventDefault()
        handleNextIssue()
      } else if (e.key.toLowerCase() === 'p') {
        e.preventDefault()
        handlePrevIssue()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [visibleBlocks, selectedBlockId, onBlockSelect, handleNextIssue, handlePrevIssue])

  const renderConfidenceBadge = (block: ParseBlock) => {
    if (block.confidence_source === 'real_engine') {
      const pct = Math.round(block.confidence * 100)
      const isLow = block.confidence < OCR_REVIEW_LOW_CONFIDENCE_THRESHOLD
      return (
        <span
          data-testid="confidence-badge"
          className={`text-[10px] font-mono px-1.5 py-0.5 rounded border font-medium ${
            isLow
              ? 'bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border-amber-300 dark:border-amber-800'
              : 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/80'
          }`}
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
      aria-label="Document blocks review panel"
      className="w-full h-full flex flex-col bg-zinc-50/30 dark:bg-zinc-950 overflow-hidden"
    >
      {/* 1. Review Toolbar: Search & Filters */}
      <div className="p-3 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 space-y-2 shrink-0 select-none">
        <div className="flex items-center gap-2">
          {/* Search Input with Clear Button */}
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400 pointer-events-none" />
            <input
              type="text"
              aria-label="Search blocks"
              placeholder="Search blocks..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-8 pr-7 py-1 rounded-md text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 focus:outline-hidden focus:ring-1 focus:ring-blue-500"
            />
            {searchTerm && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => setSearchTerm('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 p-0.5"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>

          {/* Type Filter */}
          <select
            aria-label="Filter by type"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="px-2 py-1 rounded-md text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 focus:outline-hidden focus:ring-1 focus:ring-blue-500"
          >
            <option value="all">All Types</option>
            <option value="text">Text</option>
            <option value="title">Title</option>
            <option value="table">Table</option>
            <option value="header">Header</option>
            <option value="footer">Footer</option>
            <option value="other">Other</option>
          </select>

          {/* Confidence Review Filter */}
          <select
            aria-label="Filter by confidence"
            value={confidenceFilter}
            onChange={(e) => setConfidenceFilter(e.target.value)}
            className="px-2 py-1 rounded-md text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 focus:outline-hidden focus:ring-1 focus:ring-blue-500"
          >
            <option value="all">All Confidence</option>
            <option value="low">Low confidence (&lt; 75%)</option>
            <option value="unknown">Unknown confidence</option>
            <option value="derived">Derived confidence</option>
          </select>
        </div>

        {/* 2. Review Status Summary & Next/Prev Issue Navigation */}
        <div className="flex items-center justify-between text-[11px] text-zinc-500 font-mono">
          <div>
            <span>{pageStats.total} blocks</span>
            {pageStats.low > 0 && (
              <span className="text-amber-600 dark:text-amber-400 font-medium">
                {' '}· {pageStats.low} low confidence
              </span>
            )}
            {pageStats.unknown > 0 && (
              <span> · {pageStats.unknown} unknown</span>
            )}
            {pageStats.derived > 0 && (
              <span> · {pageStats.derived} derived</span>
            )}
            {visibleBlocks.length !== pageStats.total && (
              <span className="text-zinc-400"> (Showing {visibleBlocks.length})</span>
            )}
          </div>

          {/* Issue Navigation */}
          {documentIssues.length > 0 && (
            <div className="flex items-center gap-1 font-sans">
              <button
                type="button"
                aria-label="Previous issue"
                title="Previous issue (P)"
                disabled={currentIssueIndex <= 0}
                onClick={handlePrevIssue}
                className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 disabled:opacity-30 disabled:pointer-events-none transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="text-[11px] font-mono text-zinc-600 dark:text-zinc-400 px-1">
                {currentIssueIndex >= 0
                  ? `Issue ${currentIssueIndex + 1} of ${documentIssues.length}`
                  : `${documentIssues.length} ${documentIssues.length === 1 ? 'issue' : 'issues'}`}
              </span>
              <button
                type="button"
                aria-label="Next issue"
                title="Next issue (N)"
                disabled={currentIssueIndex >= documentIssues.length - 1}
                onClick={handleNextIssue}
                className="p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 disabled:opacity-30 disabled:pointer-events-none transition-colors"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* 3. Block Detail View (Expanded when a block is selected) */}
      {selectedBlock && (
        <div
          data-testid="block-detail-panel"
          className="p-3 border-b border-amber-200 dark:border-amber-900/60 bg-amber-50/40 dark:bg-amber-950/20 shrink-0 space-y-2 select-text"
        >
          <div className="flex items-center justify-between gap-2 select-none">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">
                Block Details
              </span>
              <span className="text-[10px] font-mono text-zinc-400">
                ({selectedBlock.block_id})
              </span>
              <span
                className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded border font-semibold ${getTypeBadgeStyle(
                  selectedBlock.type
                )}`}
              >
                {selectedBlock.type.toUpperCase()}
              </span>
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={handleCopyText}
                className="px-2 py-0.5 rounded border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-[11px] font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-700 inline-flex items-center gap-1 transition-colors"
                title="Copy block text"
              >
                {copied ? (
                  <>
                    <Check className="w-3 h-3 text-emerald-500" />
                    <span className="text-emerald-600 dark:text-emerald-400">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3 h-3 text-zinc-400" />
                    <span>Copy</span>
                  </>
                )}
              </button>
              <button
                type="button"
                aria-label="Close detail"
                onClick={() => onBlockSelect(null)}
                className="p-1 rounded text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-200/50 dark:hover:bg-zinc-800 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Full content */}
          <div className="p-2 rounded bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-xs font-sans text-zinc-800 dark:text-zinc-200 max-h-24 overflow-y-auto whitespace-pre-wrap break-words">
            {selectedBlock.content || <span className="italic text-zinc-400">Empty content</span>}
          </div>

          {/* Metadata Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] font-mono">
            <div className="p-1.5 rounded bg-white/70 dark:bg-zinc-900/70 border border-zinc-200/70 dark:border-zinc-800">
              <span className="text-zinc-400 block text-[10px] uppercase font-sans">Confidence</span>
              <span className="font-semibold text-zinc-700 dark:text-zinc-200">
                {selectedBlock.confidence_source === 'real_engine'
                  ? `${Math.round(selectedBlock.confidence * 100)}%`
                  : selectedBlock.confidence_source === 'synthesized'
                  ? 'Derived'
                  : 'Unavailable'}
              </span>
            </div>

            <div className="p-1.5 rounded bg-white/70 dark:bg-zinc-900/70 border border-zinc-200/70 dark:border-zinc-800">
              <span className="text-zinc-400 block text-[10px] uppercase font-sans">Source</span>
              <span className="text-zinc-700 dark:text-zinc-200 truncate block">
                {selectedBlock.confidence_source}
              </span>
            </div>

            <div className="p-1.5 rounded bg-white/70 dark:bg-zinc-900/70 border border-zinc-200/70 dark:border-zinc-800">
              <span className="text-zinc-400 block text-[10px] uppercase font-sans">Engine</span>
              <span className="text-zinc-700 dark:text-zinc-200 truncate block">
                {selectedBlock.source_engine || 'N/A'}
              </span>
            </div>

            <div className="p-1.5 rounded bg-white/70 dark:bg-zinc-900/70 border border-zinc-200/70 dark:border-zinc-800">
              <span className="text-zinc-400 block text-[10px] uppercase font-sans">Geometry</span>
              <span className="text-zinc-700 dark:text-zinc-200 truncate block">
                {selectedBlock.bbox && selectedBlock.bbox.length >= 3
                  ? `Available (${selectedBlock.bbox.length} pts)`
                  : 'No visual region available'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* 4. Scrollable Blocks Cards List */}
      <div className="flex-1 w-full overflow-y-auto p-3 space-y-2">
        {visibleBlocks.length === 0 ? (
          <div className="w-full h-32 flex flex-col items-center justify-center text-center text-zinc-400 space-y-1">
            <Info className="w-5 h-5 text-zinc-300 dark:text-zinc-600 mb-1" />
            <span className="text-xs">No blocks match the current filter or search.</span>
            {(searchTerm || typeFilter !== 'all' || confidenceFilter !== 'all') && (
              <button
                type="button"
                onClick={() => {
                  setSearchTerm('')
                  setTypeFilter('all')
                  setConfidenceFilter('all')
                }}
                className="text-xs text-blue-600 dark:text-blue-400 hover:underline pt-1"
              >
                Reset filters
              </button>
            )}
          </div>
        ) : (
          visibleBlocks.map((block) => {
            const isSelected = block.block_id === selectedBlockId
            const isHovered = block.block_id === hoveredBlockId
            const isIssue = isReviewIssue(block.confidence, block.confidence_source)

            return (
              <button
                type="button"
                key={block.block_id}
                data-testid="block-card"
                data-block-id={block.block_id}
                ref={(el) => {
                  if (el) cardRefs.current.set(block.block_id, el)
                  else cardRefs.current.delete(block.block_id)
                }}
                aria-selected={isSelected}
                onClick={() => onBlockSelect(isSelected ? null : block.block_id)}
                onMouseEnter={() => onBlockHover(block.block_id)}
                onMouseLeave={() => onBlockHover(null)}
                className={`w-full text-left p-3 rounded-lg border transition-all cursor-pointer select-none focus:outline-hidden focus:ring-2 focus:ring-blue-500/50 block ${
                  isSelected
                    ? 'bg-amber-50/70 dark:bg-amber-950/30 border-amber-400 dark:border-amber-600 shadow-xs'
                    : isHovered
                    ? 'bg-blue-50/50 dark:bg-blue-950/20 border-blue-300 dark:border-blue-700 shadow-2xs'
                    : isIssue
                    ? 'bg-white dark:bg-zinc-900 border-amber-300/80 dark:border-amber-800/80 hover:border-amber-400 dark:hover:border-amber-700'
                    : 'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-700'
                }`}
              >
                {/* Header: Type Badge, ID, Issue Indicator, & Confidence */}
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded border font-semibold ${getTypeBadgeStyle(
                        block.type
                      )}`}
                    >
                      {block.type}
                    </span>
                    <span className="text-[10px] font-mono text-zinc-400 truncate max-w-[110px]">
                      {block.block_id}
                    </span>
                    {isIssue && (
                      <span
                        title="Review issue: low or unverified confidence"
                        className="inline-flex items-center gap-0.5 text-[9px] font-mono text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/60 px-1 py-0.2 rounded border border-amber-200 dark:border-amber-800/80"
                      >
                        <AlertTriangle className="w-2.5 h-2.5" />
                        <span>Issue</span>
                      </span>
                    )}
                  </div>

                  {renderConfidenceBadge(block)}
                </div>

                {/* Content Preview (Plain text, line-clamp-3) */}
                <p className="text-xs text-zinc-800 dark:text-zinc-200 leading-relaxed font-sans line-clamp-3 whitespace-pre-wrap break-words">
                  {block.content || <span className="italic text-zinc-400">Empty content</span>}
                </p>
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}

export default BlocksView
