import React, { useRef } from 'react'
import { UploadCloud, AlertCircle } from 'lucide-react'
import { MAX_UPLOAD_BYTES, SUPPORTED_EXTENSIONS_STRING, formatBytes } from '@/lib/utils'

interface DropzoneProps {
  onFileSelected: (file: File) => void
  isDragActive: boolean
  onDragOver: (e: React.DragEvent) => void
  onDragLeave: (e: React.DragEvent) => void
  onDrop: (e: React.DragEvent) => void
  error: string | null
}

export const Dropzone: React.FC<DropzoneProps> = ({
  onFileSelected,
  isDragActive,
  onDragOver,
  onDragLeave,
  onDrop,
  error,
}) => {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      onFileSelected(files[0])
    }
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 bg-zinc-50/50 dark:bg-zinc-950 select-none">
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`w-full max-w-xl p-10 rounded-xl border-2 border-dashed transition-all cursor-pointer flex flex-col items-center text-center ${
          isDragActive
            ? 'border-blue-500 bg-blue-50/50 dark:bg-blue-950/20 scale-[1.01]'
            : 'border-zinc-300 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 hover:border-zinc-400 dark:hover:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-900'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          data-testid="dropzone-file-input"
          aria-label="Upload document file"
          className="hidden"
          accept={SUPPORTED_EXTENSIONS_STRING}
          onChange={handleInputChange}
        />

        <div className="w-12 h-12 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-zinc-600 dark:text-zinc-300 mb-4 shadow-2xs">
          <UploadCloud className="w-6 h-6" />
        </div>

        <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
          Drop a document here
        </h3>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1 mb-5">
          or <span className="text-blue-600 dark:text-blue-400 font-medium underline underline-offset-2">browse from your computer</span>
        </p>

        {/* Supported formats */}
        <div className="w-full pt-4 border-t border-zinc-100 dark:border-zinc-800/80 text-[11px] text-zinc-500 dark:text-zinc-400 space-y-1.5">
          <div className="flex flex-wrap items-center justify-center gap-1.5">
            <span className="font-medium text-zinc-700 dark:text-zinc-300">Supported:</span>
            <span className="px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-mono">PDF</span>
            <span className="px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-mono">DOC / DOCX</span>
            <span className="px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-mono">XLS / XLSX / XLSM</span>
            <span className="px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-mono">PNG / JPG / WEBP / TIFF</span>
          </div>
          <p className="text-[11px] text-zinc-400">
            Upload limit: up to {formatBytes(MAX_UPLOAD_BYTES)} per document
          </p>
        </div>
      </div>

      {error && (
        <div className="mt-4 max-w-xl w-full p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-xs text-rose-700 dark:text-rose-300 flex items-start gap-2 animate-in fade-in">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-600" />
          <span>{error}</span>
        </div>
      )}
    </div>
  )
}
