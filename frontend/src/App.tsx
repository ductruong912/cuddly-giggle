import { useState, useRef, useCallback, useEffect } from 'react'
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
  ProcessingMode,
  ProcessingState,
  ResultData,
  UploadedDocument,
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

  // Processing configuration (single local pipeline)
  const [mode, setMode] = useState<ProcessingMode>('ocr')

  // Supporting historical document display when viewing past records
  const [historicalDoc, setHistoricalDoc] = useState<UploadedDocument | null>(null)

  // Active document representation (uploaded or historical)
  const activeDoc = document || historicalDoc

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
    isLlmError?: boolean
  } | null>(null)

  // Phase 2: Visual Inspector & Block synchronization states
  const [sourceViewMode, setSourceViewMode] = useState<'original' | 'inspector'>('original')
  const [activePageIndex, setActivePageIndex] = useState<number>(0)
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null)
  const [hoveredBlockId, setHoveredBlockId] = useState<string | null>(null)
  const [ocrTab, setOcrTab] = useState<'markdown' | 'preview' | 'blocks'>('markdown')

  // Drawer state
  const [isHistoryOpen, setIsHistoryOpen] = useState(false)
  const timerRef = useRef<number | null>(null)
  const hiddenFileInputRef = useRef<HTMLInputElement>(null)

  // Check if database history is available (via live endpoint verification)
  const hasHistory = hasPersistence

  // Clear output result when file changes
  const handleClearDocument = useCallback(() => {
    if (processing.abortController) {
      processing.abortController.abort()
    }
    clearDocument()
    setHistoricalDoc(null)
    setResult(null)
    setError(null)
    setSourceViewMode('original')
    setActivePageIndex(0)
    setSelectedBlockId(null)
    setHoveredBlockId(null)
    setOcrTab('markdown')
  }, [clearDocument, processing.abortController])

  const handleSelectFile = useCallback(
    (file: File) => {
      setHistoricalDoc(null)
      const ok = selectFile(file)
      if (ok) {
        setResult(null)
        setError(null)
        setSourceViewMode('original')
        setActivePageIndex(0)
        setSelectedBlockId(null)
        setHoveredBlockId(null)
        setOcrTab('markdown')
      }
    },
    [selectFile]
  )

  const handleHiddenFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      handleSelectFile(file)
    }
    // Reset so the same file can be selected again
    e.target.value = ''
  }

  // Run execution
  const handleRun = useCallback(async () => {
    // Only real uploaded files can be processed
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
        const parseResponse = await apiClient.parseDocument(document.file, controller.signal)
        const totalElapsed = (performance.now() - startTime) / 1000
        setResult({
          mode: 'ocr',
          markdown: parseResponse.markdown || '',
          requestTime: Date.now(),
          filename: document.name,
          elapsedSeconds: totalElapsed,
          parseResponse,
        })
        setActivePageIndex(0)
        setSelectedBlockId(null)
        setHoveredBlockId(null)
      } else {
        const extractionResponse = await apiClient.extractLocal(document.file, controller.signal)
        const totalElapsed = (performance.now() - startTime) / 1000
        setResult({
          mode: 'extraction',
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
          isLlmError: err.isLlmError,
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
  }, [document, mode])

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

  // Phase 2: Page and Block navigation handlers
  const handlePageChange = useCallback(
    (newIndex: number) => {
      setActivePageIndex(newIndex)
      setHoveredBlockId(null)
      // Clear selectedBlockId if it does not belong to the new page
      setSelectedBlockId((prevSelected) => {
        if (!prevSelected) return null
        if (result?.mode === 'ocr' && result.parseResponse) {
          const newPageBlocks = result.parseResponse.pages[newIndex]?.blocks || []
          const exists = newPageBlocks.some((b) => b.block_id === prevSelected)
          return exists ? prevSelected : null
        }
        return null
      })
    },
    [result]
  )

  const handleBlockSelect = useCallback((blockId: string | null) => {
    setSelectedBlockId(blockId)
    if (blockId) {
      setOcrTab('blocks')
    }
  }, [])

  const handleNavigateIssue = useCallback(
    (targetPageIndex: number, blockId: string) => {
      if (targetPageIndex !== activePageIndex) {
        setActivePageIndex(targetPageIndex)
      }
      setSelectedBlockId(blockId)
      setOcrTab('blocks')
    },
    [activePageIndex]
  )

  // Select historical record
  const handleSelectHistoryRecord = useCallback((record: ExtractionRecord) => {
    setSourceViewMode('original')
    setActivePageIndex(0)
    setSelectedBlockId(null)
    setHoveredBlockId(null)
    // If no file is currently uploaded, build a safe placeholder for split view
    if (!document) {
      const ext = record.source_filename.split('.').pop()?.toLowerCase() || 'pdf'
      const placeholderDoc: UploadedDocument = {
        file: new File([], record.source_filename),
        name: record.source_filename,
        size: 0,
        type: ['png', 'jpg', 'jpeg', 'tiff', 'bmp', 'webp'].includes(ext)
          ? 'image'
          : ['docx', 'xlsx'].includes(ext)
          ? 'office'
          : 'pdf',
        extension: `.${ext}`,
        previewUrl: undefined,
      }
      setHistoricalDoc(placeholderDoc)
    }

    setMode('extraction')
    setResult({
      mode: 'extraction',
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
  }, [document])

  // Global Keyboard Shortcuts (Ctrl/Cmd+O, Ctrl/Cmd+Enter, Escape)
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd + O: Open file picker
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'o') {
        e.preventDefault()
        hiddenFileInputRef.current?.click()
        return
      }

      // Ctrl/Cmd + Enter: Trigger processing
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        if (document && !processing.isProcessing) {
          e.preventDefault()
          handleRun()
        }
        return
      }

      // Escape: Dismiss active states or cancel
      if (e.key === 'Escape') {
        if (isHistoryOpen) {
          e.preventDefault()
          setIsHistoryOpen(false)
        } else if (processing.isProcessing) {
          e.preventDefault()
          handleCancel()
        }
      }
    }

    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
  }, [document, processing.isProcessing, isHistoryOpen, handleRun, handleCancel])

  return (
    <div className="w-full h-full flex flex-col bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 overflow-hidden font-sans">
      {/* Hidden file input for Ctrl+O */}
      <input
        ref={hiddenFileInputRef}
        type="file"
        data-testid="global-file-input"
        className="hidden"
        accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.webp,.docx,.xlsx,.txt,.md"
        onChange={handleHiddenFileInputChange}
        tabIndex={-1}
        aria-hidden="true"
      />

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
        document={activeDoc}
        onClearDocument={handleClearDocument}
        mode={mode}
        onChangeMode={setMode}
        processing={processing}
        onRun={handleRun}
        onCancel={handleCancel}
      />

      {/* 3. Main Workspace */}
      <main className="flex-1 w-full h-[calc(100vh-100px)] overflow-hidden flex flex-col relative">
        {!activeDoc ? (
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
            left={
              <DocumentViewer
                document={activeDoc}
                parseResponse={result?.mode === 'ocr' ? result.parseResponse : undefined}
                viewMode={sourceViewMode}
                onViewModeChange={setSourceViewMode}
                activePageIndex={activePageIndex}
                selectedBlockId={selectedBlockId}
                hoveredBlockId={hoveredBlockId}
                onPageChange={handlePageChange}
                onBlockSelect={handleBlockSelect}
                onBlockHover={setHoveredBlockId}
              />
            }
            right={
              <OutputPanel
                result={result}
                processing={processing}
                error={error}
                filename={activeDoc.name}
                mode={mode}
                onRetry={document ? handleRun : undefined}
                onSwitchToOcr={() => setMode('ocr')}
                activePageIndex={activePageIndex}
                selectedBlockId={selectedBlockId}
                hoveredBlockId={hoveredBlockId}
                onBlockSelect={handleBlockSelect}
                onBlockHover={setHoveredBlockId}
                activeOcrTab={ocrTab}
                onOcrTabChange={setOcrTab}
                onNavigateIssue={handleNavigateIssue}
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
