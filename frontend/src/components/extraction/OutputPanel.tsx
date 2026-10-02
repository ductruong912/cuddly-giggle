import React, { useState, lazy, Suspense } from 'react'
import {
  FileCode,
  Eye,
  FileSpreadsheet,
  Braces,
  CheckCircle,
  AlertCircle,
  Loader2,
  Terminal,
  RotateCcw,
  ArrowRight,
  Info,
  Boxes,
} from 'lucide-react'
import { MarkdownTab } from './MarkdownTab'
import { PoFieldsTab } from './PoFieldsTab'
import { JsonTab } from './JsonTab'
import { ValidationTab } from './ValidationTab'
import { MetadataFooter } from './MetadataFooter'
import { BlocksView } from './BlocksView'
import { Button } from '@/components/common/Button'
import type { ProcessingMode, ProcessingState, ResultData } from '@/types/document'
import { formatDuration } from '@/lib/utils'

const MarkdownPreview = lazy(() => import('./MarkdownPreview'))

interface OutputPanelProps {
  result: ResultData
  processing: ProcessingState
  error: { status?: number; message: string; detail?: string; isLlmError?: boolean } | null
  filename?: string
  mode?: ProcessingMode
  onRetry?: () => void
  onSwitchToOcr?: () => void
  activePageIndex?: number
  selectedBlockId?: string | null
  hoveredBlockId?: string | null
  onBlockSelect?: (blockId: string | null) => void
  onBlockHover?: (blockId: string | null) => void
  activeOcrTab?: 'markdown' | 'preview' | 'blocks'
  onOcrTabChange?: (tab: 'markdown' | 'preview' | 'blocks') => void
  onNavigateIssue?: (pageIndex: number, blockId: string) => void
}

function getErrorDetails(
  status?: number,
  mode: ProcessingMode = 'ocr',
  isLlm?: boolean,
  message?: string
) {
  // If it's an LLM/OpenAI error during structured extraction
  if (
    mode === 'extraction' &&
    (isLlm ||
      status === 503 ||
      message?.toLowerCase().includes('openai') ||
      message?.toLowerCase().includes('llm') ||
      message?.toLowerCase().includes('structured extraction is unavailable'))
  ) {
    return {
      title: 'Structured extraction is unavailable',
      description:
        'The backend OpenAI/LLM service is currently unavailable or unconfigured. OCR-only mode may still be available.',
      isLlmFailure: true,
    }
  }

  const prefix = mode === 'ocr' ? 'OCR' : 'Extraction'

  switch (status) {
    case 400:
      return {
        title: `${prefix} request invalid`,
        description: 'The uploaded file or request parameters are malformed.',
        isLlmFailure: false,
      }
    case 404:
      return {
        title: 'Resource not found',
        description: 'The requested extraction record or file could not be found.',
        isLlmFailure: false,
      }
    case 413:
      return {
        title: 'File exceeds size limit',
        description: 'The uploaded file exceeds the 50 MB server limit. Please upload a smaller document.',
        isLlmFailure: false,
      }
    case 415:
      return {
        title: 'Unsupported file format',
        description:
          'This file format is not supported. Please upload a PDF, image (PNG, JPG, TIFF, WEBP, BMP), Word, or Excel document.',
        isLlmFailure: false,
      }
    case 422:
      return {
        title: 'Validation failed',
        description: 'The document data could not be validated or processed according to schema constraints.',
        isLlmFailure: false,
      }
    case 429:
      return {
        title: 'Rate limit exceeded',
        description: 'Too many requests were sent in a short period. Please wait a moment before trying again.',
        isLlmFailure: false,
      }
    case 500:
      return {
        title: `${prefix} internal error`,
        description: 'An unexpected server error occurred while processing the document.',
        isLlmFailure: false,
      }
    case 503:
      return {
        title: 'Service temporarily unavailable',
        description: 'The processing engine or backing service is temporarily unable to handle requests.',
        isLlmFailure: false,
      }
    case 504:
      return {
        title: `${prefix} timed out`,
        description: 'The document processing timed out. The document may be too large or complex.',
        isLlmFailure: false,
      }
    default:
      return {
        title: `${prefix} failed`,
        description: message || 'An error occurred during processing.',
        isLlmFailure: false,
      }
  }
}

export const OutputPanel: React.FC<OutputPanelProps> = ({
  result,
  processing,
  error,
  filename = 'document',
  mode = 'ocr',
  onRetry,
  onSwitchToOcr,
  activePageIndex = 0,
  selectedBlockId = null,
  hoveredBlockId = null,
  onBlockSelect,
  onBlockHover,
  activeOcrTab,
  onOcrTabChange,
  onNavigateIssue,
}) => {
  // Tab states
  const [internalOcrTab, setInternalOcrTab] = useState<'markdown' | 'preview' | 'blocks'>('markdown')
  const [extractTab, setExtractTab] = useState<'fields' | 'json' | 'validation'>('fields')
  const [prevResult, setPrevResult] = useState<ResultData>(null)

  const currentOcrTab = activeOcrTab ?? internalOcrTab

  const setOcrTab = (tab: 'markdown' | 'preview' | 'blocks') => {
    setInternalOcrTab(tab)
    onOcrTabChange?.(tab)
  }

  // React pattern for resetting state on prop change during render
  if (result !== prevResult) {
    setPrevResult(result)
    setInternalOcrTab('markdown')
    setExtractTab('fields')
  }

  const errorInfo = error
    ? getErrorDetails(error.status, mode, error.isLlmError, error.message)
    : null

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
              <div
                role="tablist"
                aria-label="OCR output views"
                className="inline-flex p-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-xs"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={currentOcrTab === 'markdown'}
                  onClick={() => setOcrTab('markdown')}
                  className={`px-3 py-1 rounded-md font-medium inline-flex items-center gap-1.5 transition-all ${
                    currentOcrTab === 'markdown'
                      ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                      : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  <FileCode className="w-3.5 h-3.5" />
                  <span>Markdown</span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={currentOcrTab === 'preview'}
                  onClick={() => setOcrTab('preview')}
                  className={`px-3 py-1 rounded-md font-medium inline-flex items-center gap-1.5 transition-all ${
                    currentOcrTab === 'preview'
                      ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                      : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  <Eye className="w-3.5 h-3.5" />
                  <span>Preview</span>
                </button>
                {result.parseResponse && (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={currentOcrTab === 'blocks'}
                    onClick={() => setOcrTab('blocks')}
                    className={`px-3 py-1 rounded-md font-medium inline-flex items-center gap-1.5 transition-all ${
                      currentOcrTab === 'blocks'
                        ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs'
                        : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                    }`}
                  >
                    <Boxes className="w-3.5 h-3.5" />
                    <span>Blocks</span>
                  </button>
                )}
              </div>
            )}

            {/* Structured Extraction Tabs */}
            {result.mode === 'extraction' && (
              <div
                role="tablist"
                aria-label="Extraction views"
                className="inline-flex p-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-xs"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={extractTab === 'fields'}
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
                  role="tab"
                  aria-selected={extractTab === 'json'}
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
                  role="tab"
                  aria-selected={extractTab === 'validation'}
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
            <div className="max-w-md w-full p-6 rounded-xl bg-white dark:bg-zinc-900 border border-rose-200 dark:border-rose-900/60 shadow-xs space-y-4">
              <div className="flex items-center gap-3">
                <div
                  className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
                    errorInfo?.isLlmFailure
                      ? 'bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-900 text-amber-600 dark:text-amber-400'
                      : 'bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-900 text-rose-600 dark:text-rose-400'
                  }`}
                >
                  {errorInfo?.isLlmFailure ? (
                    <Info className="w-5 h-5" />
                  ) : (
                    <AlertCircle className="w-5 h-5" />
                  )}
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                    {errorInfo?.title || 'Processing Request Failed'}
                  </h4>
                  {error.status && (
                    <span className="text-[11px] font-mono text-zinc-500 dark:text-zinc-400">
                      HTTP {error.status}
                    </span>
                  )}
                </div>
              </div>

              <p className="text-xs text-zinc-700 dark:text-zinc-300 leading-relaxed">
                {errorInfo?.description || error.message}
              </p>

              {error.detail && error.detail !== error.message && (
                <div className="p-3 rounded-lg bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 font-mono text-[11px] text-zinc-600 dark:text-zinc-400 max-h-32 overflow-y-auto whitespace-pre-wrap">
                  {error.detail}
                </div>
              )}

              {/* Actions / Recovery */}
              <div className="flex items-center gap-2 pt-1 border-t border-zinc-100 dark:border-zinc-800/80">
                {errorInfo?.isLlmFailure && onSwitchToOcr && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={onSwitchToOcr}
                    icon={<ArrowRight className="w-3.5 h-3.5" />}
                    aria-label="Switch to OCR mode"
                  >
                    Switch to OCR Mode
                  </Button>
                )}

                {onRetry && (
                  <Button
                    variant={errorInfo?.isLlmFailure ? 'outline' : 'primary'}
                    size="sm"
                    onClick={onRetry}
                    icon={<RotateCcw className="w-3.5 h-3.5" />}
                    aria-label="Try again"
                  >
                    Try again
                  </Button>
                )}
              </div>
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
                {currentOcrTab === 'markdown' && (
                  <MarkdownTab markdown={result.markdown} filename={filename} />
                )}
                {currentOcrTab === 'preview' && (
                  <Suspense
                    fallback={
                      <div className="w-full h-full flex flex-col items-center justify-center p-8 bg-zinc-50/50 dark:bg-zinc-950 text-center select-none text-zinc-500">
                        <Loader2 className="w-5 h-5 animate-spin text-zinc-400 mb-2" />
                        <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Loading preview...</span>
                      </div>
                    }
                  >
                    <MarkdownPreview markdown={result.markdown} />
                  </Suspense>
                )}
                {currentOcrTab === 'blocks' && result.parseResponse && (
                  <BlocksView
                    blocks={
                      result.parseResponse.pages[activePageIndex]?.blocks ||
                      result.parseResponse.pages[0]?.blocks ||
                      []
                    }
                    readingOrder={
                      result.parseResponse.pages[activePageIndex]?.reading_order ||
                      result.parseResponse.pages[0]?.reading_order ||
                      []
                    }
                    selectedBlockId={selectedBlockId}
                    hoveredBlockId={hoveredBlockId}
                    onBlockSelect={onBlockSelect ?? (() => {})}
                    onBlockHover={onBlockHover ?? (() => {})}
                    allPages={result.parseResponse.pages}
                    activePageIndex={activePageIndex}
                    onNavigateIssue={onNavigateIssue}
                  />
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
