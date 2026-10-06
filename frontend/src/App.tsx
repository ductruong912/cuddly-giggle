import { useEffect, useRef, useState } from 'react'
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  Circle,
  Copy,
  FileCheck2,
  PanelLeft,
  PanelLeftClose,
  FileText,
  LoaderCircle,
  ScanLine,
  Upload,
  X,
} from 'lucide-react'
import {
  checkHealth,
  fetchConfig,
  fileSuffix,
  formatBytes,
  runOCR,
  validateFile,
  UIError,
} from './api'
import type { UIConfig } from './api'
import DocumentPreview from './DocumentPreview'
import MarkdownResult from './MarkdownResult'
import Settings from './Settings'
import { getMessages } from './i18n'
import { usePreferences } from './preferences'

type Status = 'idle' | 'ready' | 'processing' | 'done' | 'error'
interface Selection {
  file: File
  url: string
  id: number
}

export default function App() {
  const preferences = usePreferences()
  const { language } = preferences
  const t = getMessages(language)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const menu = useRef<HTMLButtonElement>(null)
  const sidebarClose = useRef<HTMLButtonElement>(null)
  const [config, setConfig] = useState<UIConfig | null>(null)
  const [configError, setConfigError] = useState(false)
  const [connection, setConnection] = useState<'checking' | 'online' | 'offline'>('checking')
  const [refresh, setRefresh] = useState(0)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [status, setStatus] = useState<Status>('idle')
  const [markdown, setMarkdown] = useState('')
  const [error, setError] = useState<UIError | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [outputTab, setOutputTab] = useState<'rendered' | 'source'>('rendered')
  const [mobileTab, setMobileTab] = useState<'document' | 'result'>('document')
  const [dragging, setDragging] = useState(false)
  const [copyFeedback, setCopyFeedback] = useState<'' | 'copied' | 'copyFailed'>('')
  const [documentShare, setDocumentShare] = useState(50)
  const [resizing, setResizing] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const panels = useRef<HTMLDivElement>(null)
  const output = useRef<HTMLDivElement>(null)
  const outputButtons = useRef<(HTMLButtonElement | null)[]>([])
  const mobileButtons = useRef<(HTMLButtonElement | null)[]>([])
  const activeURL = useRef<string | null>(null)
  const request = useRef<AbortController | null>(null)
  const busy = useRef(false)
  const nextID = useRef(0)
  const started = useRef(0)
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    const controller = new AbortController()
    void fetchConfig(controller.signal)
      .then((value) => {
        setConfig(value)
        setConfigError(false)
      })
      .catch(() => {
        if (!controller.signal.aborted) setConfigError(true)
      })
    void checkHealth(controller.signal)
      .then((online) => setConnection(online ? 'online' : 'offline'))
      .catch(() => {
        if (!controller.signal.aborted) setConnection('offline')
      })
    return () => controller.abort()
  }, [refresh])

  useEffect(() => {
    if (sidebarOpen) sidebarClose.current?.focus({ preventScroll: true })
  }, [sidebarOpen])

  function closeSidebar() {
    setSidebarOpen(false)
    menu.current?.focus({ preventScroll: true })
  }

  useEffect(
    () => () => {
      request.current?.abort()
      if (activeURL.current) URL.revokeObjectURL(activeURL.current)
      clearTimeout(copyTimer.current)
    },
    [],
  )

  useEffect(() => {
    if (status !== 'processing') return
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - started.current) / 1000)),
      1000,
    )
    return () => clearInterval(timer)
  }, [status])

  useEffect(() => {
    if (status === 'done') output.current?.focus({ preventScroll: true })
  }, [status])

  function chooseFiles(files: FileList | null) {
    if (busy.current || !config || !files?.length) return
    if (files.length !== 1) {
      setError(new UIError('oneFile'))
      return
    }
    const file = files[0]
    const issue = validateFile(file, config)
    if (issue) {
      setError(issue)
      return
    }
    if (activeURL.current) URL.revokeObjectURL(activeURL.current)
    const url = URL.createObjectURL(file)
    activeURL.current = url
    setSelection({ file, url, id: ++nextID.current })
    setMarkdown('')
    setError(null)
    setCopyFeedback('')
    setElapsed(0)
    setStatus('ready')
    setMobileTab('document')
    setOutputTab('rendered')
    setDocumentShare(50)
  }

  async function process() {
    if (!selection || !config || busy.current) return
    const issue = validateFile(selection.file, config)
    if (issue) {
      setError(issue)
      return
    }
    busy.current = true
    const controller = new AbortController()
    request.current = controller
    started.current = Date.now()
    setStatus('processing')
    setError(null)
    setMarkdown('')
    setCopyFeedback('')
    setElapsed(0)
    try {
      const result = await runOCR(selection.file, controller.signal)
      if (controller.signal.aborted) return
      setMarkdown(result)
      setStatus('done')
      setMobileTab('result')
    } catch (cause) {
      if (controller.signal.aborted) return
      setStatus('error')
      setError(
        cause instanceof TypeError
          ? new UIError('connectionLost')
          : cause instanceof UIError
            ? cause
            : new UIError('requestFailed'),
      )
      setMobileTab('result')
    } finally {
      busy.current = false
      if (!controller.signal.aborted) setElapsed(Math.floor((Date.now() - started.current) / 1000))
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(markdown)
      setCopyFeedback('copied')
    } catch {
      setCopyFeedback('copyFailed')
    }
    clearTimeout(copyTimer.current)
    copyTimer.current = setTimeout(() => setCopyFeedback(''), 3500)
  }

  function download() {
    if (!selection || !markdown) return
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }))
    const anchor = document.createElement('a')
    const stem =
      selection.file.name.replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|\p{Cc}]/gu, '_') || 'document'
    anchor.href = url
    anchor.download = `${stem}.md`
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const processing = status === 'processing'
  const statusLabel = {
    idle: t.choose,
    ready: t.ready,
    processing: t.processing,
    done: t.done,
    error: t.needsRetry,
  }[status]
  const connectionLabel = {
    checking: t.checking,
    online: t.online,
    offline: t.offline,
  }[connection]

  return (
    <div className={`app-shell ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <a href="#workspace" className="skip-link">
        {t.skip}
      </a>
      {sidebarOpen && (
        <button
          className="sidebar-backdrop"
          aria-label={t.closeSidebar}
          onClick={closeSidebar}
          tabIndex={-1}
        />
      )}
      <aside
        id="sidebar"
        className="sidebar"
        aria-label={t.sidebar}
        hidden={!sidebarOpen}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault()
            closeSidebar()
          }
        }}
      >
        <div className="sidebar-header">
          <span>{t.workspace}</span>
          <button
            ref={sidebarClose}
            className="icon-button"
            aria-label={t.closeSidebar}
            title={t.closeSidebar}
            onClick={closeSidebar}
          >
            <PanelLeftClose size={19} />
          </button>
        </div>
        <Settings {...preferences} />
      </aside>
      <main className="main-shell">
        <header className="topbar">
          <button
            ref={menu}
            className="icon-button menu-toggle"
            aria-controls="sidebar"
            aria-expanded={sidebarOpen}
            aria-label={sidebarOpen ? t.closeSidebar : t.openSidebar}
            title={sidebarOpen ? t.closeSidebar : t.openSidebar}
            onClick={() => (sidebarOpen ? closeSidebar() : setSidebarOpen(true))}
          >
            <PanelLeft size={19} />
          </button>
          <a className="brand" href="/" aria-label={t.home}>
            <span className="brand-mark">
              <ScanLine size={23} />
            </span>
            <span>cuddly giggle</span>
          </a>
          <h1>{t.read}</h1>
          <div className="topbar-actions">
            <button
              className={`connection ${connection}`}
              aria-label={connectionLabel}
              title={t.checkConnection}
              onClick={() => setRefresh(refresh + 1)}
            >
              <span className="status-dot" />
              <span className="connection-label">{connectionLabel}</span>
            </button>
            <a
              className="icon-button docs-link"
              href="/docs"
              target="_blank"
              rel="noreferrer"
              aria-label={t.docs}
              title={t.docs}
            >
              <BookOpen size={18} />
            </a>
          </div>
        </header>

        <input
          ref={input}
          type="file"
          id="document-upload"
          className="sr-only"
          aria-label={t.choose}
          accept={config?.supported_suffixes.join(',')}
          disabled={processing || !config}
          onChange={(event) => {
            chooseFiles(event.target.files)
            event.target.value = ''
          }}
        />
        {configError && (
          <div className="alert config-alert" role="alert">
            {t.configFailed}
            <button onClick={() => setRefresh(refresh + 1)}>{t.reconnect}</button>
          </div>
        )}
        {error && (
          <div className="alert" role="alert">
            <Circle size={16} />
            <span>{error.localizedMessage(language)}</span>
            <button
              className="icon-button"
              aria-label={t.closeAlert}
              onClick={() => setError(null)}
            >
              <X size={16} />
            </button>
          </div>
        )}

        <section
          id="workspace"
          className={`workspace ${selection ? 'has-document' : 'is-empty'} ${dragging ? 'is-dragging' : ''}`}
          aria-label={t.ocrWorkspace}
          tabIndex={-1}
          onDragOver={(event) => {
            event.preventDefault()
            if (!processing && config) setDragging(true)
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null))
              setDragging(false)
          }}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            chooseFiles(event.dataTransfer.files)
          }}
        >
          {dragging && (
            <div className="drop-overlay">
              <Upload size={32} />
              <strong>{t.drop}</strong>
            </div>
          )}
          {selection && (
            <div className="workspace-header">
              <div className="workspace-title">
                <FileText size={17} />
                <span>{selection.file.name}</span>
                <small>{formatBytes(selection.file.size, language)}</small>
              </div>
              <span className={`document-status ${status}`} role="status">
                {processing ? (
                  <LoaderCircle className="spin" size={13} />
                ) : status === 'done' ? (
                  <CheckCircle2 size={13} />
                ) : (
                  <span className="status-dot" />
                )}
                {statusLabel}
              </span>
            </div>
          )}
          {selection && (
            <div className="mobile-tabs" role="tablist" aria-label={t.displayArea}>
              {(['document', 'result'] as const).map((tab, index) => (
                <button
                  key={tab}
                  role="tab"
                  id={`mobile-tab-${tab}`}
                  aria-controls={`panel-${tab}`}
                  aria-selected={mobileTab === tab}
                  tabIndex={mobileTab === tab ? 0 : -1}
                  ref={(element) => {
                    mobileButtons.current[index] = element
                  }}
                  onClick={() => setMobileTab(tab)}
                  onKeyDown={(event) => {
                    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
                      event.preventDefault()
                      const target = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - index
                      setMobileTab(target ? 'result' : 'document')
                      mobileButtons.current[target]?.focus()
                    }
                  }}
                >
                  {tab === 'document' ? t.original : t.result}
                </button>
              ))}
            </div>
          )}
          <div
            ref={panels}
            className={`workspace-panels ${resizing ? 'is-resizing' : ''}`}
            style={
              selection
                ? {
                    gridTemplateColumns: `minmax(0, ${documentShare}fr) 10px minmax(0, ${100 - documentShare}fr)`,
                  }
                : undefined
            }
          >
            <section
              id="panel-document"
              className={`document-panel panel ${mobileTab === 'document' ? 'mobile-active' : ''}`}
              aria-label={t.original}
            >
              {selection && (
                <div className="panel-header">
                  <span>{t.original}</span>
                  <span className="panel-meta">
                    {fileSuffix(selection.file.name).slice(1).toUpperCase()}
                  </span>
                </div>
              )}
              {selection ? (
                <DocumentPreview
                  key={selection.id}
                  file={selection.file}
                  url={selection.url}
                  language={language}
                />
              ) : (
                <div className="upload-empty">
                  <div className="paper-illustration" aria-hidden="true">
                    <div className="paper-back" />
                    <div className="paper-front">
                      <ScanLine size={24} />
                      <span />
                      <span />
                      <span />
                      <div className="paper-table">
                        <i />
                        <i />
                        <i />
                        <i />
                        <i />
                        <i />
                      </div>
                    </div>
                    <span className="paper-plus">+</span>
                  </div>
                  <h2>{t.emptyTitle}</h2>
                  <p>{t.emptyHint}</p>
                  <button
                    className="primary-button upload-button"
                    disabled={!config}
                    onClick={() => input.current?.click()}
                  >
                    <Upload size={16} />
                    {t.choose}
                    <ArrowRight size={16} />
                  </button>
                  <small className="upload-limits">
                    {t.formats}
                    <span>
                      {config
                        ? t.maxSize(formatBytes(config.max_upload_bytes, language))
                        : t.loadingLimits}
                    </span>
                  </small>
                  {config && <small>{t.maxPages(config.pdf_max_pages)}</small>}
                </div>
              )}
            </section>
            {selection && (
              <div
                className="panel-divider"
                role="separator"
                tabIndex={0}
                aria-label={t.resize}
                aria-orientation="vertical"
                aria-controls="panel-document panel-result"
                aria-valuemin={25}
                aria-valuemax={75}
                aria-valuenow={documentShare}
                aria-valuetext={t.split(documentShare)}
                title={t.resizeHint}
                onPointerDown={(event) => {
                  if (event.button !== 0 || !event.isPrimary) return
                  event.preventDefault()
                  event.currentTarget.focus({ preventScroll: true })
                  event.currentTarget.setPointerCapture(event.pointerId)
                  setResizing(true)
                }}
                onPointerMove={(event) => {
                  if (!event.currentTarget.hasPointerCapture(event.pointerId) || !panels.current)
                    return
                  const bounds = panels.current.getBoundingClientRect()
                  const dividerWidth = event.currentTarget.getBoundingClientRect().width
                  const share =
                    (100 * (event.clientX - bounds.left - dividerWidth / 2)) /
                    (bounds.width - dividerWidth)
                  setDocumentShare(Math.min(75, Math.max(25, Math.round(share))))
                }}
                onPointerUp={(event) => {
                  if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                    event.currentTarget.releasePointerCapture(event.pointerId)
                  }
                }}
                onLostPointerCapture={() => setResizing(false)}
                onDoubleClick={() => setDocumentShare(50)}
                onKeyDown={(event) => {
                  const step = event.shiftKey ? 10 : 2
                  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                    event.preventDefault()
                    setDocumentShare((share) =>
                      Math.min(
                        75,
                        Math.max(25, share + (event.key === 'ArrowRight' ? step : -step)),
                      ),
                    )
                  } else if (['Home', 'End', 'Enter'].includes(event.key)) {
                    event.preventDefault()
                    setDocumentShare(event.key === 'Home' ? 25 : event.key === 'End' ? 75 : 50)
                  }
                }}
              >
                <span aria-hidden="true" />
              </div>
            )}
            {selection && (
              <section
                id="panel-result"
                className={`result-panel panel ${mobileTab === 'result' ? 'mobile-active' : ''}`}
                aria-label={t.result}
              >
                <div className="panel-header">
                  <span>{t.result}</span>
                  {markdown && (
                    <div className="output-tabs" role="tablist" aria-label={t.resultFormat}>
                      {(['rendered', 'source'] as const).map((tab, index) => (
                        <button
                          key={tab}
                          id={`output-tab-${tab}`}
                          role="tab"
                          aria-selected={outputTab === tab}
                          aria-controls="output-content"
                          tabIndex={outputTab === tab ? 0 : -1}
                          ref={(element) => {
                            outputButtons.current[index] = element
                          }}
                          onClick={() => setOutputTab(tab)}
                          onKeyDown={(event) => {
                            if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
                              event.preventDefault()
                              const target =
                                event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - index
                              setOutputTab(target ? 'source' : 'rendered')
                              outputButtons.current[target]?.focus()
                            }
                          }}
                        >
                          {tab === 'rendered' ? t.rendered : 'Markdown'}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div
                  id="output-content"
                  ref={output}
                  className="output-content"
                  role="tabpanel"
                  aria-labelledby={markdown ? `output-tab-${outputTab}` : undefined}
                  aria-label={markdown ? undefined : t.readResult}
                  tabIndex={0}
                  aria-busy={processing}
                >
                  {markdown ? (
                    outputTab === 'rendered' ? (
                      <MarkdownResult markdown={markdown} language={language} />
                    ) : (
                      <pre className="markdown-source">{markdown}</pre>
                    )
                  ) : (
                    <div className="result-empty">
                      <div className={`result-symbol ${processing ? 'processing-symbol' : ''}`}>
                        {processing ? (
                          <LoaderCircle className="spin" size={26} />
                        ) : status === 'error' ? (
                          <FileText size={26} />
                        ) : (
                          <FileCheck2 size={26} strokeWidth={1.4} />
                        )}
                      </div>
                      <h2>
                        {processing ? t.reading : status === 'error' ? t.readFailed : t.readyToRead}
                      </h2>
                      <p>
                        {processing
                          ? t.processingHint
                          : status === 'error'
                            ? t.errorHint
                            : t.readHint}
                      </p>
                      {processing ? (
                        <span className="elapsed" role="status">
                          {t.waited(elapsed)}
                        </span>
                      ) : (
                        <div className="result-placeholder" aria-hidden="true">
                          <span />
                          <span />
                          <span />
                          <div />
                          <span />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </section>
            )}
          </div>
          {selection && (
            <footer className="action-bar">
              <div className="file-actions">
                <button
                  className="secondary-button"
                  disabled={processing || !config}
                  onClick={() => input.current?.click()}
                >
                  <Upload size={15} />
                  {t.replace}
                </button>
              </div>
              <div className="output-actions">
                {markdown ? (
                  <>
                    <button
                      className="secondary-button export-button"
                      aria-label={t.copyMarkdown}
                      title={t.copyMarkdown}
                      disabled={!markdown || processing}
                      onClick={() => void copy()}
                    >
                      {copyFeedback === 'copied' ? <Check size={17} /> : <Copy size={17} />}
                      <span>{t.copy}</span>
                    </button>
                    <button
                      className="primary-button export-button"
                      aria-label={t.downloadMarkdown}
                      title={t.downloadMarkdown}
                      disabled={!markdown || processing}
                      onClick={download}
                    >
                      <ArrowDownToLine size={15} />
                      <span>{t.download}</span>
                    </button>
                  </>
                ) : (
                  <button
                    className="primary-button run-button"
                    disabled={!selection || !config || processing}
                    onClick={() => void process()}
                  >
                    {processing ? (
                      <LoaderCircle className="spin" size={16} />
                    ) : (
                      <ScanLine size={16} />
                    )}
                    {processing ? t.processingButton : status === 'error' ? t.retry : t.read}
                    {!processing && <ArrowRight size={15} />}
                  </button>
                )}
              </div>
            </footer>
          )}
          <div className="sr-only" role="status">
            {copyFeedback ? t[copyFeedback] : ''}
          </div>
          {copyFeedback && <div className="copy-toast">{copyFeedback ? t[copyFeedback] : ''}</div>}
        </section>

        {status === 'done' && <p className="completion-note">{t.completed(elapsed)}</p>}
      </main>
    </div>
  )
}
