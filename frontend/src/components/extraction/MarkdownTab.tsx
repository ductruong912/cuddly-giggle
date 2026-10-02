import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import {
  Copy,
  Check,
  Download,
  Search,
  ChevronUp,
  ChevronDown,
  X,
} from 'lucide-react'
import { copyToClipboard, downloadFile } from '@/lib/utils'

interface MarkdownTabProps {
  markdown: string
  filename: string
}

function escapeRegExp(string: string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export const MarkdownTab: React.FC<MarkdownTabProps> = ({ markdown, filename }) => {
  const [copied, setCopied] = useState(false)
  const [isSearchOpen, setIsSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0)

  const containerRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  const handleCopy = async () => {
    const ok = await copyToClipboard(markdown)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleDownload = () => {
    const mdName = filename.replace(/\.[^/.]+$/, '') + '.md'
    downloadFile(markdown, mdName, 'text/markdown')
  }

  // Keyboard shortcut listener for Ctrl/Cmd+F within Markdown tab container
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
        const activeEl = document.activeElement
        if (
          containerRef.current &&
          (containerRef.current.contains(activeEl) || activeEl === document.body)
        ) {
          e.preventDefault()
          setIsSearchOpen(true)
          setTimeout(() => {
            searchInputRef.current?.focus()
            searchInputRef.current?.select()
          }, 50)
        }
      } else if (e.key === 'Escape' && isSearchOpen) {
        e.preventDefault()
        setIsSearchOpen(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isSearchOpen])

  // Focus search input when opened
  useEffect(() => {
    if (isSearchOpen) {
      searchInputRef.current?.focus()
      searchInputRef.current?.select()
    }
  }, [isSearchOpen])

  // Count total matches and build regex
  const { totalMatches, regex } = useMemo(() => {
    const trimmed = searchQuery.trim()
    if (!trimmed) {
      return { totalMatches: 0, regex: null }
    }
    try {
      const reg = new RegExp('(' + escapeRegExp(trimmed) + ')', 'giu')
      const matches = markdown.match(reg)
      return {
        totalMatches: matches ? matches.length : 0,
        regex: reg,
      }
    } catch {
      return { totalMatches: 0, regex: null }
    }
  }, [searchQuery, markdown])

  // Safely constrain active match index during render
  const safeMatchIndex = totalMatches > 0 ? Math.min(currentMatchIndex, totalMatches - 1) : 0

  // Scroll active match into view
  useEffect(() => {
    if (isSearchOpen && totalMatches > 0) {
      const el = document.getElementById(`search-match-${safeMatchIndex}`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      }
    }
  }, [safeMatchIndex, isSearchOpen, totalMatches])

  const handleNextMatch = useCallback(() => {
    if (totalMatches === 0) return
    setCurrentMatchIndex((prev) => (prev + 1) % totalMatches)
  }, [totalMatches])

  const handlePrevMatch = useCallback(() => {
    if (totalMatches === 0) return
    setCurrentMatchIndex((prev) => (prev - 1 + totalMatches) % totalMatches)
  }, [totalMatches])

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (e.shiftKey) {
        handlePrevMatch()
      } else {
        handleNextMatch()
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setIsSearchOpen(false)
    }
  }

  // Render markdown content with highlighted matches
  const renderedContent = useMemo(() => {
    if (!isSearchOpen || !regex || totalMatches === 0) {
      return markdown
    }

    const parts = markdown.split(regex)
    let matchCounter = 0

    return parts.map((part, index) => {
      // Check if this part matches the search query (case-insensitive)
      if (part.toLowerCase() === searchQuery.trim().toLowerCase()) {
        const thisMatchIdx = matchCounter++
        const isCurrent = thisMatchIdx === safeMatchIndex
        return (
          <mark
            key={index}
            id={`search-match-${thisMatchIdx}`}
            className={`transition-colors rounded-2xs px-0.5 ${
              isCurrent
                ? 'bg-amber-400 dark:bg-amber-500 text-zinc-950 font-bold ring-2 ring-amber-500 shadow-xs'
                : 'bg-yellow-200/90 dark:bg-yellow-600/40 text-inherit'
            }`}
          >
            {part}
          </mark>
        )
      }
      return <React.Fragment key={index}>{part}</React.Fragment>
    })
  }, [markdown, isSearchOpen, regex, totalMatches, searchQuery, safeMatchIndex])

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      className="relative w-full h-full flex flex-col bg-zinc-50/50 dark:bg-zinc-950 overflow-hidden outline-hidden"
    >
      {/* Action Bar */}
      <div className="h-9 px-4 border-b border-zinc-200 dark:border-zinc-800/80 bg-white dark:bg-zinc-900 flex items-center justify-between shrink-0">
        <span className="text-[11px] font-mono text-zinc-500">
          {markdown.length.toLocaleString()} characters • {markdown.split('\n').length} lines
        </span>

        <div className="flex items-center gap-1.5">
          {/* Output Search Toggle */}
          <button
            type="button"
            onClick={() => setIsSearchOpen((prev) => !prev)}
            aria-label="Search in output (Ctrl+F)"
            title="Search in output (Ctrl+F)"
            className={`h-7 px-2 rounded text-xs font-medium inline-flex items-center gap-1 transition-colors ${
              isSearchOpen
                ? 'bg-zinc-200/80 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100'
                : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800'
            }`}
          >
            <Search className="w-3.5 h-3.5" />
            <span className="text-[11px] hidden sm:inline">Find</span>
          </button>

          <button
            type="button"
            onClick={handleCopy}
            aria-label="Copy raw markdown to clipboard"
            className="h-7 px-2.5 rounded text-xs font-medium inline-flex items-center gap-1.5 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-500" />
                <span className="text-emerald-600 dark:text-emerald-400">Copied</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span>Copy</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={handleDownload}
            aria-label="Download markdown file"
            className="h-7 px-2.5 rounded text-xs font-medium inline-flex items-center gap-1.5 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download .md</span>
          </button>
        </div>
      </div>

      {/* Compact Search Bar (Ctrl+F) */}
      {isSearchOpen && (
        <div className="h-9 px-3 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-100/90 dark:bg-zinc-900/90 backdrop-blur-xs flex items-center justify-between gap-2 shrink-0 animate-in fade-in slide-in-from-top-1 duration-150">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <Search className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="Find in document... (Enter = next, Shift+Enter = prev)"
              aria-label="Find in document"
              className="bg-transparent text-xs text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-hidden w-full"
            />
          </div>

          <div className="flex items-center gap-1 shrink-0 select-none">
            {/* Match Counter e.g. "2 / 5" */}
            {searchQuery.trim() && (
              <span className="text-[11px] font-mono px-1.5 text-zinc-500 dark:text-zinc-400">
                {totalMatches === 0 ? '0 / 0' : `${safeMatchIndex + 1} / ${totalMatches}`}
              </span>
            )}

            {/* Prev Match */}
            <button
              type="button"
              onClick={handlePrevMatch}
              disabled={totalMatches === 0}
              aria-label="Previous match"
              title="Previous match (Shift+Enter)"
              className="p-1 rounded text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-zinc-800 disabled:opacity-30 disabled:pointer-events-none transition-colors"
            >
              <ChevronUp className="w-3.5 h-3.5" />
            </button>

            {/* Next Match */}
            <button
              type="button"
              onClick={handleNextMatch}
              disabled={totalMatches === 0}
              aria-label="Next match"
              title="Next match (Enter)"
              className="p-1 rounded text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-zinc-800 disabled:opacity-30 disabled:pointer-events-none transition-colors"
            >
              <ChevronDown className="w-3.5 h-3.5" />
            </button>

            {/* Close */}
            <button
              type="button"
              onClick={() => setIsSearchOpen(false)}
              aria-label="Close search"
              title="Close search (Esc)"
              className="p-1 rounded text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-zinc-800 transition-colors ml-1"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Editor-like Monospace Display */}
      <div className="flex-1 w-full h-full p-4 overflow-auto font-mono text-xs leading-relaxed text-zinc-800 dark:text-zinc-200 select-text whitespace-pre-wrap selection:bg-blue-100 dark:selection:bg-blue-900/60">
        {renderedContent}
      </div>
    </div>
  )
}
