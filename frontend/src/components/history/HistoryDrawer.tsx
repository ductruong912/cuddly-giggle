import React, { useState, useEffect, useMemo, useCallback } from 'react'
import {
  FileText,
  Calendar,
  Clock,
  Layers,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  RefreshCw,
  Hash,
  Search,
  X,
} from 'lucide-react'
import { Drawer } from '@/components/common/Drawer'
import { Badge } from '@/components/common/Badge'
import { apiClient } from '@/api/client'
import { formatDuration } from '@/lib/utils'
import type { ExtractionRecord } from '@/types/api'

interface HistoryDrawerProps {
  isOpen: boolean
  onClose: () => void
  onSelectExtraction: (record: ExtractionRecord) => void
}

type StatusFilter = 'all' | 'valid' | 'needs_review'

export const HistoryDrawer: React.FC<HistoryDrawerProps> = ({
  isOpen,
  onClose,
  onSelectExtraction,
}) => {
  const [loading, setLoading] = useState(false)
  const [records, setRecords] = useState<ExtractionRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loadingRecordId, setLoadingRecordId] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const fetchHistory = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await apiClient.getExtractions({ limit: 50 })
      setRecords(response.items || [])
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : 'Extraction history is not available (persistence disabled).'
      )
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!isOpen) return
    let isCancelled = false

    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await apiClient.getExtractions({ limit: 50 })
        if (!isCancelled) {
          setRecords(response.items || [])
        }
      } catch (err: unknown) {
        if (!isCancelled) {
          setError(
            err instanceof Error
              ? err.message
              : 'Extraction history is not available (persistence disabled).'
          )
        }
      } finally {
        if (!isCancelled) {
          setLoading(false)
        }
      }
    }

    load()

    return () => {
      isCancelled = true
    }
  }, [isOpen])

  const handleSelect = async (requestId: string) => {
    setLoadingRecordId(requestId)
    try {
      const fullRecord = await apiClient.getExtraction(requestId)
      onSelectExtraction(fullRecord)
      onClose()
    } catch (err) {
      console.error('Failed to load extraction details:', err)
    } finally {
      setLoadingRecordId(null)
    }
  }

  // Filter records by search term and validation status
  const filteredRecords = useMemo(() => {
    return records.filter((rec) => {
      // 1. Status filter
      if (statusFilter === 'valid' && rec.validation_status !== 'valid') {
        return false
      }
      if (statusFilter === 'needs_review' && rec.validation_status === 'valid') {
        return false
      }

      // 2. Search query filter (filename or PO number)
      if (searchTerm.trim()) {
        const query = searchTerm.toLowerCase().trim()
        const matchName = rec.source_filename?.toLowerCase().includes(query)
        const matchPo = rec.po_number?.toLowerCase().includes(query)
        if (!matchName && !matchPo) return false
      }

      return true
    })
  }, [records, searchTerm, statusFilter])

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title="Extraction History"
      subtitle="Past Purchase Order extractions stored in PostgreSQL"
      width="max-w-lg"
    >
      <div className="space-y-4">
        {/* Search & Filter Toolbar */}
        {!error && (
          <div className="space-y-2.5">
            {/* Search Input */}
            <div className="relative flex items-center">
              <Search className="w-3.5 h-3.5 absolute left-3 text-zinc-400 pointer-events-none" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search filename or PO number..."
                aria-label="Filter history"
                className="w-full pl-8 pr-8 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-hidden focus:ring-1 focus:ring-zinc-400 dark:focus:ring-zinc-600"
              />
              {searchTerm && (
                <button
                  type="button"
                  onClick={() => setSearchTerm('')}
                  aria-label="Clear search"
                  className="absolute right-2.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Status Filter Pills & Refresh */}
            <div className="flex items-center justify-between gap-2 text-xs">
              <div className="inline-flex p-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800 text-[11px]">
                <button
                  type="button"
                  onClick={() => setStatusFilter('all')}
                  className={`px-2.5 py-0.5 rounded font-medium transition-colors ${
                    statusFilter === 'all'
                      ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                      : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
                  }`}
                >
                  All
                </button>
                <button
                  type="button"
                  onClick={() => setStatusFilter('valid')}
                  className={`px-2.5 py-0.5 rounded font-medium transition-colors ${
                    statusFilter === 'valid'
                      ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                      : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
                  }`}
                >
                  Valid
                </button>
                <button
                  type="button"
                  onClick={() => setStatusFilter('needs_review')}
                  className={`px-2.5 py-0.5 rounded font-medium transition-colors ${
                    statusFilter === 'needs_review'
                      ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                      : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
                  }`}
                >
                  Needs review
                </button>
              </div>

              <button
                type="button"
                onClick={fetchHistory}
                disabled={loading}
                aria-label="Refresh history"
                className="inline-flex items-center gap-1 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors"
              >
                <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
                <span className="text-[11px]">Refresh</span>
              </button>
            </div>
          </div>
        )}

        {loading && records.length === 0 && (
          <div className="py-12 flex flex-col items-center justify-center text-zinc-400 gap-2">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="text-xs">Loading extractions...</span>
          </div>
        )}

        {error && (
          <div className="p-4 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-xs text-zinc-600 dark:text-zinc-300">
            {error}
          </div>
        )}

        {!loading && !error && records.length === 0 && (
          <div className="py-12 text-center text-xs text-zinc-400">
            No past extractions found in database.
          </div>
        )}

        {!loading && !error && records.length > 0 && filteredRecords.length === 0 && (
          <div className="py-12 text-center text-xs text-zinc-400">
            No extractions match your search or filter.
          </div>
        )}

        {filteredRecords.length > 0 && (
          <div className="space-y-2.5">
            {filteredRecords.map((rec) => (
              <div
                key={rec.request_id}
                onClick={() => handleSelect(rec.request_id)}
                className="p-3.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 hover:border-zinc-300 dark:hover:border-zinc-700 hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 transition-all cursor-pointer shadow-2xs space-y-2 select-none"
              >
                {/* Header row */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <FileText className="w-4 h-4 text-zinc-500 shrink-0" />
                    <span
                      className="text-xs font-semibold text-zinc-900 dark:text-zinc-100 truncate"
                      title={rec.source_filename}
                    >
                      {rec.source_filename}
                    </span>
                  </div>

                  <Badge
                    variant={
                      rec.validation_status === 'valid' ? 'success' : 'warning'
                    }
                    className="shrink-0 text-[10px]"
                  >
                    {rec.validation_status === 'valid' ? (
                      <CheckCircle2 className="w-3 h-3" />
                    ) : (
                      <AlertTriangle className="w-3 h-3" />
                    )}
                    <span>{rec.validation_status}</span>
                  </Badge>
                </div>

                {/* Details row */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-zinc-500 dark:text-zinc-400 font-mono">
                  {rec.po_number && (
                    <div className="flex items-center gap-1">
                      <Hash className="w-3 h-3 text-zinc-400" />
                      <span>PO #{rec.po_number}</span>
                    </div>
                  )}

                  <div className="flex items-center gap-1">
                    <Layers className="w-3 h-3 text-zinc-400" />
                    <span>
                      {rec.page_count} {rec.page_count === 1 ? 'page' : 'pages'}
                    </span>
                  </div>

                  {rec.duration_ms !== null && rec.duration_ms !== undefined && (
                    <div className="flex items-center gap-1">
                      <Clock className="w-3 h-3 text-zinc-400" />
                      <span>{formatDuration(rec.duration_ms / 1000)}</span>
                    </div>
                  )}

                  <div className="flex items-center gap-1">
                    <Calendar className="w-3 h-3 text-zinc-400" />
                    <span>
                      {new Date(rec.created_at).toLocaleDateString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  </div>
                </div>

                {loadingRecordId === rec.request_id && (
                  <div className="pt-1 flex items-center gap-1.5 text-xs text-blue-600 font-medium">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    <span>Loading record...</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </Drawer>
  )
}
