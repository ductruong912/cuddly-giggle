import React from 'react'
import {
  Play,
  X,
  FileCode,
  FileSpreadsheet,
  FileText,
  Image as ImageIcon,
  StopCircle,
} from 'lucide-react'
import { Button } from '@/components/common/Button'
import { formatBytes, formatDuration } from '@/lib/utils'
import type {
  ExtractionEngine,
  ProcessingMode,
  ProcessingState,
  UploadedDocument,
} from '@/types/document'

interface ToolbarProps {
  document: UploadedDocument | null
  onClearDocument: () => void
  mode: ProcessingMode
  onChangeMode: (mode: ProcessingMode) => void
  engine: ExtractionEngine
  onChangeEngine: (engine: ExtractionEngine) => void
  processing: ProcessingState
  onRun: () => void
  onCancel: () => void
}

export const Toolbar: React.FC<ToolbarProps> = ({
  document,
  onClearDocument,
  mode,
  onChangeMode,
  engine,
  onChangeEngine,
  processing,
  onRun,
  onCancel,
}) => {
  const getFileIcon = () => {
    if (!document) return null
    switch (document.type) {
      case 'image':
        return <ImageIcon className="w-3.5 h-3.5 text-blue-500" />
      case 'pdf':
        return <FileText className="w-3.5 h-3.5 text-rose-500" />
      case 'office':
        return document.extension.includes('xls') ? (
          <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-500" />
        ) : (
          <FileCode className="w-3.5 h-3.5 text-indigo-500" />
        )
      default:
        return <FileText className="w-3.5 h-3.5 text-zinc-500" />
    }
  }

  return (
    <div className="h-12 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/70 dark:bg-zinc-900/60 px-4 flex items-center justify-between gap-4 shrink-0 select-none">
      {/* Left: Document details */}
      <div className="flex items-center gap-2 min-w-0 flex-1">
        {document ? (
          <div className="flex items-center gap-2 min-w-0 max-w-sm sm:max-w-md">
            <span className="shrink-0">{getFileIcon()}</span>
            <span
              className="text-xs font-medium text-zinc-900 dark:text-zinc-100 truncate"
              title={document.name}
            >
              {document.name}
            </span>
            <span className="text-[11px] text-zinc-500 font-mono shrink-0">
              ({formatBytes(document.size)})
            </span>
            {!processing.isProcessing && (
              <button
                type="button"
                onClick={onClearDocument}
                className="p-1 rounded text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-200/60 dark:hover:bg-zinc-800 transition-colors"
                title="Remove file"
                aria-label="Remove file"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        ) : (
          <span className="text-xs text-zinc-400 dark:text-zinc-500 italic">
            No document selected
          </span>
        )}
      </div>

      {/* Middle: Mode & Engine selectors */}
      <div className="flex items-center gap-2">
        {/* Mode Segmented Control */}
        <div className="inline-flex p-0.5 rounded-lg bg-zinc-200/80 dark:bg-zinc-800 border border-zinc-300/60 dark:border-zinc-700/60 text-xs">
          <button
            type="button"
            disabled={processing.isProcessing}
            onClick={() => onChangeMode('ocr')}
            className={`px-3 py-1 rounded-md font-medium transition-all ${
              mode === 'ocr'
                ? 'bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-xs'
                : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >
            OCR
          </button>
          <button
            type="button"
            disabled={processing.isProcessing}
            onClick={() => onChangeMode('extraction')}
            className={`px-3 py-1 rounded-md font-medium transition-all ${
              mode === 'extraction'
                ? 'bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-xs'
                : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >
            Structured Extraction
          </button>
        </div>

        {/* Engine selector (only visible for Structured Extraction) */}
        {mode === 'extraction' && (
          <div className="inline-flex p-0.5 rounded-lg bg-zinc-200/80 dark:bg-zinc-800 border border-zinc-300/60 dark:border-zinc-700/60 text-xs animate-in fade-in duration-150">
            <button
              type="button"
              disabled={processing.isProcessing}
              onClick={() => onChangeEngine('local')}
              className={`px-2.5 py-1 rounded-md font-medium transition-all ${
                engine === 'local'
                  ? 'bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-xs'
                  : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
              title="Local OCR engine + LLM structured PO extraction"
            >
              Local
            </button>
            <button
              type="button"
              disabled={true}
              className="px-2.5 py-1 rounded-md font-medium text-zinc-400 dark:text-zinc-600 cursor-not-allowed"
              title="Online extraction engine is not configured on this server"
            >
              Online
            </button>
          </div>
        )}
      </div>

      {/* Right: Run / Cancel Button & Timer */}
      <div className="flex items-center gap-2">
        {processing.isProcessing && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-zinc-600 dark:text-zinc-400">
              {formatDuration(processing.elapsedSeconds)}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={onCancel}
              icon={<StopCircle className="w-3.5 h-3.5 text-rose-500" />}
              title="Cancel current processing request"
            >
              Cancel
            </Button>
          </div>
        )}

        <Button
          variant="primary"
          size="sm"
          disabled={!document || processing.isProcessing}
          loading={processing.isProcessing}
          onClick={onRun}
          icon={!processing.isProcessing ? <Play className="w-3.5 h-3.5 fill-current" /> : undefined}
        >
          {processing.isProcessing
            ? 'Processing...'
            : mode === 'ocr'
            ? 'Run OCR'
            : 'Extract'}
        </Button>
      </div>
    </div>
  )
}
