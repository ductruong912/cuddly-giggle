import React, { useState } from 'react'
import { Copy, Check, Download } from 'lucide-react'
import { copyToClipboard, downloadFile } from '@/lib/utils'

interface MarkdownTabProps {
  markdown: string
  filename: string
}

export const MarkdownTab: React.FC<MarkdownTabProps> = ({ markdown, filename }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    const ok = await copyToClipboard(markdown)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleDownload = () => {
    const mdName = filename.replace(/\.[^/.]+$/, '') + '.md'
    downloadFile(markdown, mdName, 'text/markdown')
  }

  return (
    <div className="relative w-full h-full flex flex-col bg-zinc-50/50 dark:bg-zinc-950 overflow-hidden">
      {/* Action Bar */}
      <div className="h-9 px-4 border-b border-zinc-200 dark:border-zinc-800/80 bg-white dark:bg-zinc-900 flex items-center justify-between shrink-0">
        <span className="text-[11px] font-mono text-zinc-500">
          {markdown.length.toLocaleString()} characters • {markdown.split('\n').length} lines
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={handleCopy}
            className="h-7 px-2.5 rounded text-xs font-medium inline-flex items-center gap-1.5 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-500" />
                <span className="text-emerald-600 dark:text-emerald-400">Copied</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span>Copy</span>
              </>
            )}
          </button>
          <button
            type="button"
            onClick={handleDownload}
            className="h-7 px-2.5 rounded text-xs font-medium inline-flex items-center gap-1.5 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download .md</span>
          </button>
        </div>
      </div>

      {/* Editor-like Monospace Display */}
      <div className="flex-1 w-full h-full p-4 overflow-auto font-mono text-xs leading-relaxed text-zinc-800 dark:text-zinc-200 select-text whitespace-pre-wrap selection:bg-blue-100 dark:selection:bg-blue-900/60">
        {markdown}
      </div>
    </div>
  )
}
