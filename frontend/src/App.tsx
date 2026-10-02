import { useState, useRef, useCallback } from 'react'
import { TopBar } from '@/components/layout/TopBar'
import { Toolbar } from '@/components/layout/Toolbar'
import { SplitPane } from '@/components/layout/SplitPane'
import { Dropzone } from '@/components/document/Dropzone'
import { DocumentViewer } from '@/components/document/DocumentViewer'
import { OutputPanel } from '@/components/extraction/OutputPanel'
import { HistoryDrawer } from '@/components/history/HistoryDrawer'
import { useHealth } from '@/hooks/useHealth'
import { useTheme } from '@/hooks/useTheme'
import { useDocument } from '@/hooks/useDocument'
import { apiClient } from '@/api/client'
import { ApiError } from '@/api/errors'
import type {
  ExtractionEngine,
  ProcessingMode,
  ProcessingState,
  ResultData,
} from '@/types/document'
import type { ExtractionRecord } from '@/types/api'

export default function App() {
  // Global hooks
  const { theme, toggleTheme } = useTheme()
  const {
    status,
    readiness,
    hasPersistence,
    errorDetail,
    refresh: refreshHealth,
  } = useHealth()
  const {
    document,
    error: docError,
    isDragActive,
    selectFile,
    clearDocument,
    onDragOver,
    onDragLeave,
    onDrop,
  } = useDocument()

  // Processing configuration
  const [mode, setMode] = useState<ProcessingMode>('ocr')
  const [engine, setEngine] = useState<ExtractionEngine>('local')

  // Processing & telemetry state
  const [processing, setProcessing] = useState<ProcessingState>({
    isProcessing: false,
    startTime: null,
    elapsedSeconds: 0,
    statusMessage: '',
    abortController: null,
  })

  // Results & Errors
  const [result, setResult] = useState<ResultData>(null)
  const [error, setError] = useState<{
    status?: number
    message: string
    detail?: string
  } | null>(null)

  // Drawer state
  const [isHistoryOpen, setIsHistoryOpen] = useState(false)
  const timerRef = useRef<number | null>(null)

  // Check if database history is available (via live endpoint verification)
  const hasHistory = hasPersistence

  // Clear output result when file changes
  const handleClearDocument = useCallback(() => {
    if (processing.abortController) {
      processing.abortController.abort()
    }
    clearDocument()
    setResult(null)
    setError(null)
  }, [clearDocument, processing.abortController])

  const handleSelectFile = useCallback(
    (file: File) => {
      const ok = selectFile(file)
      if (ok) {
        setResult(null)
        setError(null)
      }
    },
    [selectFile]
  )

  // Run execution
  const handleRun = useCallback(async () => {
    if (!document) return

    const controller = new AbortController()
    const startTime = performance.now()

    setError(null)
    setProcessing({
      isProcessing: true,
      startTime,
      elapsedSeconds: 0,
      statusMessage:
        mode === 'ocr'
          ? 'Running OCR on document...'
          : 'Extracting structured data...',
      abortController: controller,
    })

    // Start elapsed timer
    timerRef.current = window.setInterval(() => {
      const now = performance.now()
      setProcessing((prev) => ({
        ...prev,
        elapsedSeconds: (now - startTime) / 1000,
      }))
    }, 100)

    try {
      if (mode === 'ocr') {
        const markdown = await apiClient.ocrDocument(document.file, controller.signal)
        const totalElapsed = (performance.now() - startTime) / 1000
        setResult({
          mode: 'ocr',
          markdown,
          requestTime: Date.now(),
          filename: document.name,
          elapsedSeconds: totalElapsed,
        })
      } else {
        const extractionResponse =
          engine === 'local'
            ? await apiClient.extractLocal(document.file, controller.signal)
            : await apiClient.extractOnline(document.file, controller.signal)

        const totalElapsed = (performance.now() - startTime) / 1000
        setResult({
          mode: 'extraction',
          engine,
          response: extractionResponse,
          requestTime: Date.now(),
          filename: document.name,
          elapsedSeconds: totalElapsed,
        })
      }
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isAborted) {
        // Request cancelled intentionally
        return
      }

      if (err instanceof ApiError) {
        setError({
          status: err.status,
          message: err.message,
          detail: err.detail,
        })
      } else {
        setError({
          message: err instanceof Error ? err.message : 'Unknown error during execution.',
        })
      }
    } finally {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
      setProcessing((prev) => ({
        ...prev,
        isProcessing: false,
        abortController: null,
      }))
    }
  }, [document, mode, engine])

  const handleCancel = useCallback(() => {
    if (processing.abortController) {
      processing.abortController.abort()
    }
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    setProcessing((prev) => ({
      ...prev,
      isProcessing: false,
      abortController: null,
    }))
  }, [processing.abortController])

  // Select historical record
  const handleSelectHistoryRecord = useCallback((record: ExtractionRecord) => {
    setMode('extraction')
    setResult({
      mode: 'extraction',
      engine: 'local',
      response: {
        request_id: record.request_id,
        ocr: {
          decision: record.engine || 'local',
          page_count: record.page_count,
        },
        data: record.data,
        validation: {
          status: record.validation_status,
          attempts: record.attempts,
          healed: record.healed,
          issues: record.issues,
        },
      },
      requestTime: new Date(record.created_at).getTime(),
      filename: record.source_filename,
      elapsedSeconds: (record.duration_ms || 0) / 1000,
    })
    setError(null)
  }, [])

  return (
    <div className="w-full h-full flex flex-col bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 overflow-hidden font-sans">
      {/* 1. Top Bar */}
      <TopBar
        status={status}
        readiness={readiness}
        errorDetail={errorDetail}
        onRefreshHealth={refreshHealth}
        onOpenHistory={() => setIsHistoryOpen(true)}
        hasHistory={hasHistory}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      {/* 2. Document Processing Toolbar */}
      <Toolbar
        document={document}
        onClearDocument={handleClearDocument}
        mode={mode}
        onChangeMode={setMode}
        engine={engine}
        onChangeEngine={setEngine}
        processing={processing}
        onRun={handleRun}
        onCancel={handleCancel}
      />

      {/* 3. Main Workspace */}
      <main className="flex-1 w-full h-[calc(100vh-100px)] overflow-hidden flex flex-col relative">
        {!document ? (
          <Dropzone
            onFileSelected={handleSelectFile}
            isDragActive={isDragActive}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            error={docError}
          />
        ) : (
          <SplitPane
            left={<DocumentViewer document={document} />}
            right={
              <OutputPanel
                result={result}
                processing={processing}
                error={error}
                filename={document.name}
              />
            }
          />
        )}
      </main>

      {/* 4. History Drawer */}
      <HistoryDrawer
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
        onSelectExtraction={handleSelectHistoryRecord}
      />
    </div>
  )
}
