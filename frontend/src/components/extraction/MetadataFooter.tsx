import React from 'react'
import { CheckCircle2, Clock, Layers, Hash, Cpu } from 'lucide-react'
import { formatDuration } from '@/lib/utils'
import type { ResultData } from '@/types/document'

interface MetadataFooterProps {
  result: ResultData
}

export const MetadataFooter: React.FC<MetadataFooterProps> = ({ result }) => {
  if (!result) return null

  const requestId =
    result.mode === 'extraction' ? result.response.request_id : undefined
  const pageCount =
    result.mode === 'extraction' ? result.response.ocr.page_count : undefined

  return (
    <div className="h-8 px-4 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 flex items-center justify-between text-[11px] font-mono text-zinc-500 shrink-0 select-none overflow-x-auto">
      {/* Left: Completion status & Engine */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 font-medium">
          <CheckCircle2 className="w-3.5 h-3.5" />
          <span>Completed</span>
        </div>

        <div className="flex items-center gap-1 text-zinc-600 dark:text-zinc-400">
          <Cpu className="w-3 h-3 text-zinc-400" />
          <span>
            {result.mode === 'ocr'
              ? 'Local OCR'
              : result.engine === 'local'
              ? 'Local Pipeline'
              : 'Online Engine'}
          </span>
        </div>

        {pageCount !== undefined && (
          <div className="flex items-center gap-1 text-zinc-600 dark:text-zinc-400">
            <Layers className="w-3 h-3 text-zinc-400" />
            <span>
              {pageCount} {pageCount === 1 ? 'page' : 'pages'}
            </span>
          </div>
        )}
      </div>

      {/* Right: Latency & Request ID */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1 text-zinc-600 dark:text-zinc-400">
          <Clock className="w-3 h-3 text-zinc-400" />
          <span>{formatDuration(result.elapsedSeconds)}</span>
        </div>

        {requestId && (
          <div className="flex items-center gap-1 text-zinc-500" title={requestId}>
            <Hash className="w-3 h-3 text-zinc-400" />
            <span className="truncate max-w-[130px]">{requestId}</span>
          </div>
        )}
      </div>
    </div>
  )
}
