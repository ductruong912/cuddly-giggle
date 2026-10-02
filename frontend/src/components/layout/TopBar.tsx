import React from 'react'
import {
  FileText,
  Activity,
  History,
  Sun,
  Moon,
  Laptop,
  RefreshCw,
} from 'lucide-react'
import { Popover } from '@/components/common/Popover'
import type { BackendStatus } from '@/types/document'
import type { ReadyzResponse } from '@/types/api'
import type { Theme } from '@/hooks/useTheme'

interface TopBarProps {
  status: BackendStatus
  readiness: ReadyzResponse | null
  errorDetail: string | null
  onRefreshHealth: () => void
  onOpenHistory: () => void
  hasHistory: boolean
  theme: Theme
  onToggleTheme: () => void
}

export const TopBar: React.FC<TopBarProps> = ({
  status,
  readiness,
  errorDetail,
  onRefreshHealth,
  onOpenHistory,
  hasHistory,
  theme,
  onToggleTheme,
}) => {
  const getStatusBadge = () => {
    switch (status) {
      case 'ready':
        return (
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-800/60 hover:bg-emerald-100/60 transition-colors">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span>Ready</span>
          </div>
        )
      case 'degraded':
        return (
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/50 border border-amber-200 dark:border-amber-800/60 hover:bg-amber-100/60 transition-colors">
            <span className="w-2 h-2 rounded-full bg-amber-500" />
            <span>Degraded</span>
          </div>
        )
      case 'offline':
        return (
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium text-rose-700 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/50 border border-rose-200 dark:border-rose-800/60 hover:bg-rose-100/60 transition-colors">
            <span className="w-2 h-2 rounded-full bg-rose-500" />
            <span>Offline</span>
          </div>
        )
      case 'checking':
      default:
        return (
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium text-zinc-600 dark:text-zinc-400 bg-zinc-100 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700">
            <span className="w-2 h-2 rounded-full bg-zinc-400 animate-ping" />
            <span>Checking...</span>
          </div>
        )
    }
  }

  const renderReadinessPopoverContent = () => (
    <div className="space-y-3">
      <div className="flex items-center justify-between pb-2 border-b border-zinc-100 dark:border-zinc-800">
        <div className="flex items-center gap-1.5 font-semibold text-xs text-zinc-900 dark:text-zinc-100">
          <Activity className="w-3.5 h-3.5" />
          <span>System Readiness</span>
        </div>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onRefreshHealth()
          }}
          className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          title="Refresh health checks"
        >
          <RefreshCw className="w-3 h-3" />
        </button>
      </div>

      {readiness ? (
        <div className="space-y-2 text-xs">
          <div className="grid grid-cols-2 gap-1.5">
            <div className="flex items-center justify-between p-1.5 rounded bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-100 dark:border-zinc-800">
              <span className="text-zinc-600 dark:text-zinc-400">VL Runtime</span>
              <span
                className={
                  readiness.checks.vl_runtime === 'ok'
                    ? 'text-emerald-600 font-medium'
                    : 'text-amber-600 font-medium'
                }
              >
                {readiness.checks.vl_runtime}
              </span>
            </div>
            <div className="flex items-center justify-between p-1.5 rounded bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-100 dark:border-zinc-800">
              <span className="text-zinc-600 dark:text-zinc-400">LLM Key</span>
              <span
                className={
                  readiness.checks.llm_credentials === 'ok'
                    ? 'text-emerald-600 font-medium'
                    : 'text-rose-600 font-medium'
                }
              >
                {readiness.checks.llm_credentials}
              </span>
            </div>
            <div className="flex items-center justify-between p-1.5 rounded bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-100 dark:border-zinc-800">
              <span className="text-zinc-600 dark:text-zinc-400">Stages</span>
              <span
                className={
                  readiness.checks.stages === 'ok'
                    ? 'text-emerald-600 font-medium'
                    : 'text-amber-600 font-medium'
                }
              >
                {readiness.checks.stages}
              </span>
            </div>
            <div className="flex items-center justify-between p-1.5 rounded bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-100 dark:border-zinc-800">
              <span className="text-zinc-600 dark:text-zinc-400">Database</span>
              <span
                className={
                  readiness.checks.database === 'ok'
                    ? 'text-emerald-600 font-medium'
                    : 'text-zinc-500 font-medium'
                }
              >
                {readiness.checks.database}
              </span>
            </div>
          </div>

          {readiness.stages && (
            <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800">
              <span className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider block mb-1">
                Active Slots
              </span>
              <div className="space-y-1">
                {Object.entries(readiness.stages).map(([stage, info]) => (
                  <div key={stage} className="flex justify-between text-[11px] text-zinc-600 dark:text-zinc-400">
                    <span className="capitalize">{stage}</span>
                    <span className="font-mono text-zinc-800 dark:text-zinc-200">
                      {info.active} / {info.max_concurrency} active
                      {info.waiting > 0 && ` (${info.waiting} queued)`}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="text-xs text-zinc-500 dark:text-zinc-400 py-2">
          {errorDetail || 'Unable to fetch readiness details from /readyz.'}
        </div>
      )}
    </div>
  )

  return (
    <header className="h-[52px] border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-4 flex items-center justify-between shrink-0 select-none">
      {/* Left: Product Brand */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-7 h-7 rounded-md bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 shadow-xs">
          <FileText className="w-4 h-4" />
        </div>
        <div className="flex items-baseline gap-2">
          <span className="font-semibold text-sm tracking-tight text-zinc-900 dark:text-zinc-100">
            Cuddly OCR
          </span>
          <span className="text-[11px] text-zinc-500 font-mono hidden sm:inline">
            Playground
          </span>
        </div>
      </div>

      {/* Right: Actions & Status */}
      <div className="flex items-center gap-2">
        {/* Extraction History Button */}
        <button
          type="button"
          onClick={onOpenHistory}
          disabled={!hasHistory}
          className={`h-8 px-2.5 rounded-md text-xs font-medium inline-flex items-center gap-1.5 transition-colors ${
            hasHistory
              ? 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800'
              : 'text-zinc-400 dark:text-zinc-600 cursor-not-allowed opacity-60'
          }`}
          title={hasHistory ? 'View extraction history' : 'Database persistence not enabled'}
        >
          <History className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">History</span>
        </button>

        {/* Backend Status Indicator with Popover */}
        <Popover trigger={getStatusBadge()} content={renderReadinessPopoverContent()} align="right" />

        {/* Theme Toggle */}
        <button
          type="button"
          onClick={onToggleTheme}
          className="h-8 w-8 rounded-md flex items-center justify-center text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          title={`Theme: ${theme}`}
          aria-label="Toggle color theme"
        >
          {theme === 'light' && <Sun className="w-4 h-4" />}
          {theme === 'dark' && <Moon className="w-4 h-4" />}
          {theme === 'system' && <Laptop className="w-4 h-4" />}
        </button>
      </div>
    </header>
  )
}
