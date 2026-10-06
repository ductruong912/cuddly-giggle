import { useEffect, useRef, useState } from 'react'
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Copy,
  FileCheck2,
  FilePlus2,
  FileText,
  LoaderCircle,
  Menu,
  ScanLine,
  Sparkles,
  Upload,
  X,
} from 'lucide-react'
import { checkHealth, fetchConfig, fileSuffix, formatBytes, runOCR, validateFile } from './api'
import type { UIConfig } from './api'
import DocumentPreview from './DocumentPreview'
import MarkdownResult from './MarkdownResult'

type Status = 'idle' | 'ready' | 'processing' | 'done' | 'error'
interface Selection {
  file: File
  url: string
  id: number
}

export default function App() {
  const [config, setConfig] = useState<UIConfig | null>(null)
  const [configError, setConfigError] = useState('')
  const [connection, setConnection] = useState<'checking' | 'online' | 'offline'>('checking')
  const [refresh, setRefresh] = useState(0)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [status, setStatus] = useState<Status>('idle')
  const [markdown, setMarkdown] = useState('')
  const [error, setError] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [outputTab, setOutputTab] = useState<'rendered' | 'source'>('rendered')
  const [mobileTab, setMobileTab] = useState<'document' | 'result'>('document')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [copyFeedback, setCopyFeedback] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const menu = useRef<HTMLButtonElement>(null)
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
        setConfigError('')
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setConfigError('Chưa tải được cấu hình upload. Kiểm tra API rồi kết nối lại.')
      })
    void checkHealth(controller.signal)
      .then((online) => setConnection(online ? 'online' : 'offline'))
      .catch(() => {
        if (!controller.signal.aborted) setConnection('offline')
      })
    return () => controller.abort()
  }, [refresh])

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

  function chooseFiles(files: FileList | null) {
    if (busy.current || !config || !files?.length) return
    if (files.length !== 1) {
      setError('Mỗi lần chỉ xử lý một tài liệu. Hãy chọn một file.')
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
    setError('')
    setCopyFeedback('')
    setElapsed(0)
    setStatus('ready')
    setMobileTab('document')
    setOutputTab('rendered')
  }

  function reset() {
    if (busy.current) return
    if (activeURL.current) URL.revokeObjectURL(activeURL.current)
    activeURL.current = null
    setSelection(null)
    setMarkdown('')
    setError('')
    setCopyFeedback('')
    setElapsed(0)
    setStatus('idle')
    setMobileTab('document')
    closeSidebar()
    if (input.current) input.current.value = ''
  }

  function closeSidebar() {
    if (sidebarOpen) menu.current?.focus()
    setSidebarOpen(false)
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
    setError('')
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
          ? 'Mất kết nối với máy chủ. Yêu cầu có thể vẫn đang được xử lý; hãy kiểm tra kết nối trước khi thử lại.'
          : cause instanceof Error
            ? cause.message
            : 'Không xử lý được tài liệu. Hãy thử lại.',
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
      setCopyFeedback('Đã sao chép')
    } catch {
      setCopyFeedback('Không sao chép được. Hãy tải file Markdown.')
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
    idle: 'Chưa có tài liệu',
    ready: 'Sẵn sàng xử lý',
    processing: 'Đang xử lý',
    done: 'Đã hoàn tất',
    error: 'Chưa hoàn tất',
  }[status]
  const connectionLabel = {
    checking: 'Đang kết nối API',
    online: 'API đã kết nối',
    offline: 'API chưa kết nối',
  }[connection]

  return (
    <div className="app-shell">
      <a href="#workspace" className="skip-link">
        Đến vùng làm việc
      </a>
      {sidebarOpen && (
        <button className="sidebar-backdrop" aria-label="Đóng điều hướng" onClick={closeSidebar} />
      )}
      <aside
        id="main-navigation"
        className={`sidebar ${sidebarOpen ? 'is-open' : ''}`}
        onKeyDown={(event) => {
          if (event.key === 'Escape') closeSidebar()
        }}
      >
        <a className="brand" href="/" aria-label="OCR Playground — trang chính">
          <span className="brand-mark">
            <ScanLine size={23} />
          </span>
          <span>
            folio<span className="brand-dot">.</span>
          </span>
        </a>
        <div className="workspace-label">
          <span className="workspace-avatar">F</span>
          <div>
            Không gian nội bộ<small>Document workspace</small>
          </div>
          <ChevronRight size={14} />
        </div>
        <p className="nav-caption">KHÔNG GIAN LÀM VIỆC</p>
        <nav aria-label="Điều hướng">
          <a
            href="#workspace"
            className="nav-item active"
            aria-current="page"
            onClick={closeSidebar}
          >
            <ScanLine size={18} />
            OCR Playground<span className="nav-count">01</span>
          </a>
          <button className="nav-item" onClick={reset} disabled={processing}>
            <FilePlus2 size={18} />
            Tài liệu mới
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="local-note">
            <span className="local-dot" />
            <strong>Đọc tài liệu tại máy chủ</strong>
            <p>Không gian gọn gàng để chuyển tài liệu thành nội dung có thể sử dụng.</p>
          </div>
          <a className="nav-item docs-link" href="/docs" target="_blank" rel="noreferrer">
            <BookOpen size={17} />
            Tài liệu API
            <ArrowRight size={14} />
          </a>
          <div className="sidebar-footer">
            <span>FOLIO / OCR</span>
            <span>v0.1</span>
          </div>
        </div>
      </aside>

      <main className="main-shell">
        <header className="topbar">
          <button
            className="icon-button menu-toggle"
            ref={menu}
            aria-label="Mở điều hướng"
            aria-controls="main-navigation"
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            <Menu size={20} />
          </button>
          <div className="breadcrumb">
            <span>Không gian làm việc</span>
            <ChevronRight size={13} />
            <strong>OCR Playground</strong>
          </div>
          <button
            className={`connection ${connection}`}
            title="Kiểm tra lại kết nối API"
            onClick={() => setRefresh(refresh + 1)}
          >
            <span className="status-dot" />
            {connectionLabel}
          </button>
        </header>

        <section className="intro">
          <div>
            <p className="eyebrow">
              <span />
              TÀI LIỆU THÀNH NỘI DUNG
            </p>
            <h1>
              OCR Playground<span className="heading-dot">.</span>
            </h1>
            <p className="intro-description">Đọc tài liệu. Giữ lại cấu trúc. Sẵn sàng sử dụng.</p>
          </div>
          <div className="workflow-steps" aria-label="Quy trình">
            <span className={selection ? 'step-complete' : 'step-current'}>
              <i>{selection ? <Check size={12} /> : '1'}</i>Chọn tài liệu
            </span>
            <ChevronRight size={13} />
            <span
              className={processing ? 'step-current' : status === 'done' ? 'step-complete' : ''}
            >
              <i>{status === 'done' ? <Check size={12} /> : '2'}</i>Đọc / OCR
            </span>
            <ChevronRight size={13} />
            <span className={status === 'done' ? 'step-current' : ''}>
              <i>3</i>Xem kết quả
            </span>
          </div>
        </section>

        <input
          ref={input}
          type="file"
          id="document-upload"
          className="sr-only"
          aria-label="Chọn tài liệu"
          accept={config?.supported_suffixes.join(',')}
          disabled={processing || !config}
          onChange={(event) => {
            chooseFiles(event.target.files)
            event.target.value = ''
          }}
        />
        {configError && (
          <div className="alert config-alert" role="alert">
            {configError}
            <button onClick={() => setRefresh(refresh + 1)}>Kết nối lại</button>
          </div>
        )}
        {error && (
          <div className="alert" role="alert">
            <Circle size={16} />
            <span>{error}</span>
            <button
              className="icon-button"
              aria-label="Đóng thông báo"
              onClick={() => setError('')}
            >
              <X size={16} />
            </button>
          </div>
        )}

        <section
          id="workspace"
          className={`workspace ${dragging ? 'is-dragging' : ''}`}
          aria-label="Vùng làm việc OCR"
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
              <strong>Thả tài liệu để bắt đầu</strong>
            </div>
          )}
          <div className="workspace-header">
            <div className="workspace-title">
              <FileText size={17} />
              <span>{selection?.file.name ?? 'Không gian tài liệu'}</span>
              {selection && <small>{formatBytes(selection.file.size)}</small>}
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
          <div className="mobile-tabs" role="tablist" aria-label="Vùng hiển thị">
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
                {tab === 'document' ? 'Bản gốc' : 'Kết quả'}
              </button>
            ))}
          </div>
          <div className="workspace-panels">
            <section
              id="panel-document"
              className={`document-panel panel ${mobileTab === 'document' ? 'mobile-active' : ''}`}
              aria-label="Bản gốc"
            >
              <div className="panel-header">
                <span>
                  <span className="panel-number">01</span>Bản gốc
                </span>
                <span className="panel-meta">
                  {selection ? fileSuffix(selection.file.name).slice(1).toUpperCase() : 'INPUT'}
                </span>
              </div>
              {selection ? (
                <DocumentPreview key={selection.id} file={selection.file} url={selection.url} />
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
                    <span className="paper-plus">
                      <PlusIcon />
                    </span>
                  </div>
                  <p className="empty-eyebrow">MỖI TÀI LIỆU, MỘT KHỞI ĐẦU</p>
                  <h2>Đặt tài liệu của bạn ở đây</h2>
                  <p>
                    Kéo thả file vào không gian này
                    <br />
                    hoặc chọn từ máy tính của bạn.
                  </p>
                  <button
                    className="primary-button upload-button"
                    disabled={!config}
                    onClick={() => input.current?.click()}
                  >
                    <Upload size={16} />
                    Chọn tài liệu
                    <ArrowRight size={16} />
                  </button>
                  <div className="format-tags">
                    <span>PDF</span>
                    <span>WORD</span>
                    <span>EXCEL</span>
                    <span>ẢNH</span>
                  </div>
                  <small>
                    {config
                      ? `Tối đa ${formatBytes(config.max_upload_bytes)} / file`
                      : 'Đang tải giới hạn upload…'}
                  </small>
                </div>
              )}
            </section>
            <section
              id="panel-result"
              className={`result-panel panel ${mobileTab === 'result' ? 'mobile-active' : ''}`}
              aria-label="Kết quả"
            >
              <div className="panel-header">
                <span>
                  <span className="panel-number">02</span>Kết quả
                </span>
                <div className="output-tabs" role="tablist" aria-label="Định dạng kết quả">
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
                      {tab === 'rendered' ? 'Trình bày' : 'Markdown'}
                    </button>
                  ))}
                </div>
              </div>
              <div
                id="output-content"
                className="output-content"
                role="tabpanel"
                aria-labelledby={`output-tab-${outputTab}`}
                tabIndex={0}
                aria-busy={processing}
              >
                {markdown ? (
                  outputTab === 'rendered' ? (
                    <MarkdownResult markdown={markdown} />
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
                      {processing
                        ? 'Đang đọc tài liệu của bạn'
                        : status === 'error'
                          ? 'Chưa có kết quả OCR'
                          : 'Nội dung sẽ xuất hiện ở đây'}
                    </h2>
                    <p>
                      {processing
                        ? 'Tài liệu nhiều trang có thể cần thêm thời gian.'
                        : status === 'error'
                          ? 'Kiểm tra thông báo lỗi rồi thử lại khi sẵn sàng.'
                          : 'Văn bản và bảng trong tài liệu được chuyển\nthành Markdown để bạn xem và sử dụng.'}
                    </p>
                    {processing ? (
                      <span className="elapsed" role="status">
                        Đã chờ {elapsed} giây
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
                    {!selection && (
                      <span className="result-hint">
                        <Sparkles size={13} />
                        Từ bản gốc đến nội dung có cấu trúc
                      </span>
                    )}
                  </div>
                )}
              </div>
            </section>
          </div>
          <footer className="action-bar">
            <div className="file-actions">
              <button
                className="secondary-button"
                disabled={processing || !config}
                onClick={() => input.current?.click()}
              >
                <Upload size={15} />
                {selection ? 'Đổi file' : 'Chọn file'}
              </button>
              <span className="file-action-hint">
                {selection
                  ? `${fileSuffix(selection.file.name).slice(1).toUpperCase()} · ${formatBytes(selection.file.size)}`
                  : 'Một tài liệu mỗi lần xử lý'}
              </span>
            </div>
            <div className="output-actions">
              <button
                className="icon-button export-button"
                aria-label="Sao chép Markdown"
                disabled={!markdown || processing}
                onClick={() => void copy()}
              >
                {copyFeedback === 'Đã sao chép' ? <Check size={17} /> : <Copy size={17} />}
              </button>
              <button
                className="secondary-button export-button"
                disabled={!markdown || processing}
                onClick={download}
              >
                <ArrowDownToLine size={15} />
                <span>Tải Markdown</span>
              </button>
              <span className="action-divider" />
              <button
                className="primary-button run-button"
                disabled={!selection || !config || processing}
                onClick={() => void process()}
              >
                {processing ? <LoaderCircle className="spin" size={16} /> : <ScanLine size={16} />}
                {processing ? 'Đang xử lý…' : status === 'error' ? 'Thử lại OCR' : 'Chạy OCR'}
                {!processing && <ArrowRight size={15} />}
              </button>
            </div>
          </footer>
          <div className="sr-only" role="status">
            {copyFeedback}
          </div>
          {copyFeedback && <div className="copy-toast">{copyFeedback}</div>}
        </section>

        <footer className="page-footer">
          <span>
            PDF, Word, Excel & ảnh<span className="footer-dot">·</span>Đọc tài liệu tại máy chủ
          </span>
          <span>
            {config ? `PDF cần OCR: tối đa ${config.pdf_max_pages} trang` : 'OCR Playground'}
            <span className="footer-dot">·</span>
            {status === 'done' ? `${elapsed} giây` : 'Markdown output'}
          </span>
        </footer>
      </main>
    </div>
  )
}

function PlusIcon() {
  return <span>+</span>
}
