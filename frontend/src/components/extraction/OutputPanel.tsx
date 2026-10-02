import React, { useState } from 'react'
import {
  FileCode,
  Eye,
  FileSpreadsheet,
  Braces,
  CheckCircle,
  AlertCircle,
  Loader2,
  Terminal,
} from 'lucide-react'
import { MarkdownTab } from './MarkdownTab'
import { MarkdownPreview } from './MarkdownPreview'
import { PoFieldsTab } from './PoFieldsTab'
import { JsonTab } from './JsonTab'
import { ValidationTab } from './ValidationTab'
import { MetadataFooter } from './MetadataFooter'
import type { ProcessingState, ResultData } from '@/types/document'
import { formatDuration } from '@/lib/utils'

interface OutputPanelProps {
  result: ResultData
  processing: ProcessingState
  error: { status?: number; message: string; detail?: string } | null
  filename?: string
}

export const OutputPanel: React.FC<OutputPanelProps> = ({
  result,
  processing,
  error,
  filename = 'document',
}) => {
  // Tab states
  const [ocrTab, setOcrTab] = useState<'markdown' | 'preview'>('markdown')
  const [extractTab, setExtractTab] = useState<'fields' | 'json' | 'validation'>('fields')
  const [prevResult, setPrevResult] = useState<ResultData>(null)

  // React-recommended pattern for resetting state on prop change during render
  if (result !== prevResult) {
    setPrevResult(result)
    setOcrTab('markdown')
    setExtractTab('fields')
  }

  return (
    <div className="w-full h-full flex flex-col bg-white dark:bg-zinc-950 overflow-hidden relative">
      {/* Tab Navigation Header (Only when a result is available and not currently processing) */}
      {result && !processing.isProcessing && (
        <div className="h-10 px-4 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 flex items-center justify-between shrink-0 select-none">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              Output
            </span>
            <span className="text-xs text-zinc-400 dark:text-zinc-600">•</span>

            {/* OCR Tabs */}
            {result.mode === 'ocr' && (
              <div className="inline-flex p-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-xs">
                <button
                  type="button"
                  onClick={() => setOcrTab('markdown')}
                  className={`px-3 py-1 rounded-md font-medium inline-flex items-center gap-1.5 transition-all ${
                    ocrTab === 'markdown'
                      ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                      : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  <FileCode className="w-3.5 h-3.5" />
                  <span>Markdown</span>
                </button>
                <button
                  type="button"
                  onClick={() => setOcrTab('preview')}
                  className={`px-3 py-1 rounded-md font-medium inline-flex items-center gap-1.5 transition-all ${
                    ocrTab === 'preview'
                      ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                      : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  <Eye className="w-3.5 h-3.5" />
                  <span>Preview</span>
                </button>
              </div>
            )}

            {/* Structured Extraction Tabs */}
            {result.mode === 'extraction' && (
              <div className="inline-flex p-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-xs">
                <button
                  type="button"
                  onClick={() => setExtractTab('fields')}
                  className={`px-3 py-1 rounded-md font-medium inline-flex items-center gap-1.5 transition-all ${
                    extractTab === 'fields'
                      ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                      : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  <FileSpreadsheet className="w-3.5 h-3.5" />
                  <span>Fields</span>
                </button>
                <button
                  type="button"
                  onClick={() => setExtractTab('json')}
                  className={`px-3 py-1 rounded-md font-medium inline-flex items-center gap-1.5 transition-all ${
                    extractTab === 'json'
                      ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                      : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  <Braces className="w-3.5 h-3.5" />
                  <span>JSON</span>
                </button>
                <button
                  type="button"
                  onClick={() => setExtractTab('validation')}
                  className={`px-3 py-1 rounded-md font-medium inline-flex items-center gap-1.5 transition-all ${
                    extractTab === 'validation'
                      ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                      : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  <CheckCircle className="w-3.5 h-3.5" />
                  <span>Validation</span>
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 w-full h-full overflow-hidden relative">
        {/* State 1: Active Processing */}
        {processing.isProcessing && (
          <div className="w-full h-full flex flex-col items-center justify-center p-8 bg-zinc-50/50 dark:bg-zinc-950 text-center select-none">
            <div className="max-w-sm w-full p-6 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-xs flex flex-col items-center space-y-4">
              <div className="w-12 h-12 rounded-full bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-400">
                <Loader2 className="w-6 h-6 animate-spin" />
              </div>

              <div>
                <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                  {processing.statusMessage || 'Processing document...'}
                </h4>
                <p className="text-xs text-zinc-500 mt-1">
                  Parsing layout and optical characters.
                </p>
              </div>

              {/* Indeterminate animated progress bar */}
              <div className="w-full bg-zinc-100 dark:bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                <div className="bg-blue-600 h-1.5 rounded-full w-2/5 animate-[indeterminate_1.5s_infinite_ease-in-out]" />
              </div>

              <div className="text-xs font-mono text-zinc-400">
                Elapsed: {formatDuration(processing.elapsedSeconds)}
              </div>
            </div>
          </div>
        )}

        {/* State 2: Error State */}
        {!processing.isProcessing && error && (
          <div className="w-full h-full flex flex-col items-center justify-center p-8 bg-zinc-50/50 dark:bg-zinc-950">
            <div className="max-w-md w-full p-6 rounded-xl bg-white dark:bg-zinc-900 border border-rose-200 dark:border-rose-900/60 shadow-xs space-y-3">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-900 text-rose-600 dark:text-rose-400 flex items-center justify-center shrink-0">
                  <AlertCircle className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                    Processing Request Failed
                  </h4>
                  {error.status && (
                    <span className="text-[11px] font-mono text-rose-600 dark:text-rose-400">
                      HTTP {error.status}
                    </span>
                  )}
                </div>
              </div>

              <p className="text-xs text-zinc-700 dark:text-zinc-300 leading-relaxed">
                {error.message}
              </p>

              {error.detail && error.detail !== error.message && (
                <div className="p-3 rounded-lg bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 font-mono text-[11px] text-zinc-600 dark:text-zinc-400 max-h-36 overflow-y-auto whitespace-pre-wrap">
                  {error.detail}
                </div>
              )}
            </div>
          </div>
        )}

        {/* State 3: Empty State (No result yet) */}
        {!processing.isProcessing && !error && !result && (
          <div className="w-full h-full flex flex-col items-center justify-center p-8 bg-zinc-50/40 dark:bg-zinc-950 text-center select-none">
            <div className="w-12 h-12 rounded-xl bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 flex items-center justify-center text-zinc-400 mb-3 shadow-2xs">
              <Terminal className="w-6 h-6" />
            </div>
            <h4 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              Run OCR to see the result.
            </h4>
            <p className="text-xs text-zinc-400 dark:text-zinc-500 mt-1 max-w-xs">
              Choose OCR or Structured Extraction above, then click the primary action button to execute.
            </p>
          </div>
        )}

        {/* State 4: Results Display */}
        {!processing.isProcessing && !error && result && (
          <div className="w-full h-full overflow-hidden flex flex-col">
            {result.mode === 'ocr' ? (
              <div className="flex-1 w-full h-full overflow-hidden">
                {ocrTab === 'markdown' ? (
                  <MarkdownTab markdown={result.markdown} filename={filename} />
                ) : (
                  <MarkdownPreview markdown={result.markdown} />
                )}
              </div>
            ) : (
              <div className="flex-1 w-full h-full overflow-hidden">
                {extractTab === 'fields' && <PoFieldsTab response={result.response} />}
                {extractTab === 'json' && (
                  <JsonTab data={result.response} filename={filename} />
                )}
                {extractTab === 'validation' && (
                  <ValidationTab validation={result.response.validation} />
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Metadata Footer */}
      {!processing.isProcessing && result && <MetadataFooter result={result} />}
    </div>
  )
}
