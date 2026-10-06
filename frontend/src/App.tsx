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
  FilePlus2,
  FileText,
  LoaderCircle,
  ScanLine,
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
  const [dragging, setDragging] = useState(false)
  const [copyFeedback, setCopyFeedback] = useState('')
  const [documentShare, setDocumentShare] = useState(50)
  const [resizing, setResizing] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const panels = useRef<HTMLDivElement>(null)
  const workspace = useRef<HTMLElement>(null)
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

  useEffect(() => {
    if (status === 'done') output.current?.focus({ preventScroll: true })
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
    setDocumentShare(50)
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
    setDocumentShare(50)
    if (input.current) input.current.value = ''
    workspace.current?.focus({ preventScroll: true })
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
    idle: 'Chọn tài liệu',
    ready: 'Sẵn sàng',
    processing: 'Đang xử lý',
    done: 'Hoàn tất',
    error: 'Cần thử lại',
  }[status]
  const connectionLabel = {
    checking: 'Đang kết nối',
    online: 'Đã kết nối',
    offline: 'Mất kết nối',
  }[connection]

  return (
    <div className="app-shell">
      <a href="#workspace" className="skip-link">
        Đến vùng làm việc
      </a>
      <main className="main-shell">
        <header className="topbar">
          <a className="brand" href="/" aria-label="cuddly giggle — trang chính">
            <span className="brand-mark">
              <ScanLine size={23} />
            </span>
            <span>cuddly giggle</span>
          </a>
          <h1>Đọc tài liệu</h1>
          <div className="topbar-actions">
            {selection && (
              <button
                className="secondary-button new-document"
                onClick={reset}
                disabled={processing}
              >
                <FilePlus2 size={17} />
                Tài liệu mới
              </button>
            )}
            <button
              className={`connection ${connection}`}
              title="Kiểm tra lại kết nối"
              onClick={() => setRefresh(refresh + 1)}
            >
              <span className="status-dot" />
              {connectionLabel}
            </button>
            <a
              className="icon-button docs-link"
              href="/docs"
              target="_blank"
              rel="noreferrer"
              aria-label="Tài liệu API"
              title="Tài liệu API"
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
          ref={workspace}
          className={`workspace ${selection ? 'has-document' : 'is-empty'} ${dragging ? 'is-dragging' : ''}`}
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
          {selection && (
            <div className="workspace-header">
              <div className="workspace-title">
                <FileText size={17} />
                <span>{selection.file.name}</span>
                <small>{formatBytes(selection.file.size)}</small>
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
              aria-label="Bản gốc"
            >
              {selection && (
                <div className="panel-header">
                  <span>Bản gốc</span>
                  <span className="panel-meta">
                    {fileSuffix(selection.file.name).slice(1).toUpperCase()}
                  </span>
                </div>
              )}
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
                    <span className="paper-plus">+</span>
                  </div>
                  <h2>Tài liệu của bạn, dễ đọc hơn.</h2>
                  <p>Kéo thả file vào đây hoặc</p>
                  <button
                    className="primary-button upload-button"
                    disabled={!config}
                    onClick={() => input.current?.click()}
                  >
                    <Upload size={16} />
                    Chọn tài liệu
                    <ArrowRight size={16} />
                  </button>
                  <small className="upload-limits">
                    PDF, Word, Excel, ảnh
                    <span>
                      {config
                        ? `Tối đa ${formatBytes(config.max_upload_bytes)}`
                        : 'Đang tải giới hạn…'}
                    </span>
                  </small>
                  {config && <small>PDF cần OCR: tối đa {config.pdf_max_pages} trang</small>}
                </div>
              )}
            </section>
            {selection && (
              <div
                className="panel-divider"
                role="separator"
                tabIndex={0}
                aria-label="Điều chỉnh độ rộng bản gốc và kết quả"
                aria-orientation="vertical"
                aria-controls="panel-document panel-result"
                aria-valuemin={25}
                aria-valuemax={75}
                aria-valuenow={documentShare}
                aria-valuetext={`Bản gốc ${documentShare}% · Kết quả ${100 - documentShare}%`}
                title="Kéo để đổi độ rộng. Nhấp đúp hoặc nhấn Enter để chia đều."
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
                aria-label="Kết quả"
              >
                <div className="panel-header">
                  <span>Kết quả</span>
                  {markdown && (
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
                  )}
                </div>
                <div
                  id="output-content"
                  ref={output}
                  className="output-content"
                  role="tabpanel"
                  aria-labelledby={markdown ? `output-tab-${outputTab}` : undefined}
                  aria-label={markdown ? undefined : 'Kết quả đọc tài liệu'}
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
                          ? 'Đang đọc tài liệu…'
                          : status === 'error'
                            ? 'Chưa đọc được tài liệu'
                            : 'Sẵn sàng đọc'}
                      </h2>
                      <p>
                        {processing
                          ? 'Tài liệu nhiều trang có thể cần thêm thời gian.'
                          : status === 'error'
                            ? 'Kiểm tra thông báo và thử lại.'
                            : 'Nhấn “Đọc tài liệu” để bắt đầu.'}
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
                  Đổi file
                </button>
              </div>
              <div className="output-actions">
                {markdown ? (
                  <>
                    <button
                      className="secondary-button export-button"
                      aria-label="Sao chép Markdown"
                      title="Sao chép Markdown"
                      disabled={!markdown || processing}
                      onClick={() => void copy()}
                    >
                      {copyFeedback === 'Đã sao chép' ? <Check size={17} /> : <Copy size={17} />}
                      <span>Sao chép</span>
                    </button>
                    <button
                      className="primary-button export-button"
                      aria-label="Tải Markdown"
                      title="Tải Markdown"
                      disabled={!markdown || processing}
                      onClick={download}
                    >
                      <ArrowDownToLine size={15} />
                      <span>Tải xuống</span>
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
                    {processing ? 'Đang xử lý…' : status === 'error' ? 'Thử lại' : 'Đọc tài liệu'}
                    {!processing && <ArrowRight size={15} />}
                  </button>
                )}
              </div>
            </footer>
          )}
          <div className="sr-only" role="status">
            {copyFeedback}
          </div>
          {copyFeedback && <div className="copy-toast">{copyFeedback}</div>}
        </section>

        {status === 'done' && <p className="completion-note">Đã đọc xong · {elapsed} giây</p>}
      </main>
    </div>
  )
}
