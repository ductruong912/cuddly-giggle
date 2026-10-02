import React from 'react'
import { FileSpreadsheet, FileText, CheckCircle2, ShieldCheck } from 'lucide-react'
import { formatBytes } from '@/lib/utils'

interface OfficeViewerProps {
  name: string
  extension: string
  size: number
}

export const OfficeViewer: React.FC<OfficeViewerProps> = ({
  name,
  extension,
  size,
}) => {
  const isExcel = ['.xls', '.xlsx', '.xlsm'].includes(extension.toLowerCase())

  return (
    <div className="w-full h-full flex flex-col items-center justify-center p-8 bg-zinc-50 dark:bg-zinc-950 text-center select-none">
      <div className="max-w-md w-full p-8 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-xs flex flex-col items-center">
        {/* Document Icon */}
        <div
          className={`w-16 h-16 rounded-xl flex items-center justify-center mb-4 ${
            isExcel
              ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
              : 'bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800'
          }`}
        >
          {isExcel ? (
            <FileSpreadsheet className="w-8 h-8" />
          ) : (
            <FileText className="w-8 h-8" />
          )}
        </div>

        {/* File Details */}
        <h3
          className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 max-w-full truncate px-2"
          title={name}
        >
          {name}
        </h3>
        <div className="flex items-center gap-2 mt-1 mb-4 text-xs font-mono text-zinc-500">
          <span className="uppercase font-semibold px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
            {extension.replace('.', '')}
          </span>
          <span>•</span>
          <span>{formatBytes(size)}</span>
        </div>

        {/* Informative message */}
        <div className="w-full pt-4 border-t border-zinc-100 dark:border-zinc-800/80 space-y-2 text-xs text-zinc-600 dark:text-zinc-400">
          <div className="flex items-center justify-center gap-1.5 text-emerald-600 dark:text-emerald-400 font-medium">
            <CheckCircle2 className="w-4 h-4" />
            <span>Ready for processing</span>
          </div>
          <p className="text-[11px] leading-relaxed text-zinc-500 dark:text-zinc-400">
            Browser preview is unavailable for {isExcel ? 'Excel spreadsheets' : 'Word documents'},
            but full native parsing and text extraction are supported by the backend engines.
          </p>
          <div className="flex items-center justify-center gap-1 text-[11px] text-zinc-400 dark:text-zinc-500 pt-1">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Local privacy preserved — no third-party rendering used.</span>
          </div>
        </div>
      </div>
    </div>
  )
}
