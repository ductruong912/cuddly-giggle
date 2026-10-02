import React from 'react'
import { CheckCircle2, AlertTriangle, Sparkles, ShieldCheck } from 'lucide-react'
import { Badge } from '@/components/common/Badge'
import type { ExtractionValidation } from '@/types/api'

interface ValidationTabProps {
  validation?: ExtractionValidation | null
}

export const ValidationTab: React.FC<ValidationTabProps> = ({ validation }) => {
  const status = validation?.status === 'valid' ? 'valid' : 'needs_review'
  const isValid = status === 'valid'
  const attempts = typeof validation?.attempts === 'number' ? validation.attempts : 1
  const healed = Boolean(validation?.healed)
  const issues = Array.isArray(validation?.issues) ? validation.issues : []

  return (
    <div className="w-full h-full p-6 overflow-auto bg-zinc-50/40 dark:bg-zinc-950 space-y-6">
      {/* Top Validation Overview Banner */}
      <div
        className={`p-4 rounded-xl border transition-all ${
          isValid
            ? 'bg-emerald-50/40 dark:bg-emerald-950/20 border-emerald-200/80 dark:border-emerald-800/50'
            : 'bg-amber-50/40 dark:bg-amber-950/20 border-amber-200/80 dark:border-amber-800/50'
        }`}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div
              className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
                isValid
                  ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400'
                  : 'bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400'
              }`}
            >
              {isValid ? (
                <CheckCircle2 className="w-5 h-5" />
              ) : (
                <AlertTriangle className="w-5 h-5" />
              )}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                  {isValid ? 'Record Fully Validated' : 'Review Recommended'}
                </span>
                <Badge variant={isValid ? 'success' : 'warning'}>
                  {status}
                </Badge>
              </div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                {isValid
                  ? 'All arithmetic invariants and schema constraints passed deterministic checks.'
                  : 'Some line item totals or header constraints drifted beyond relative tolerance.'}
              </p>
            </div>
          </div>

          {/* Metrics summary */}
          <div className="flex items-center gap-3 text-xs border-t sm:border-t-0 pt-3 sm:pt-0 border-zinc-200/60 dark:border-zinc-800 shrink-0">
            <div className="px-3 py-1.5 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800">
              <span className="text-zinc-500 block text-[10px] uppercase font-medium">
                Attempts
              </span>
              <span className="font-mono font-semibold text-zinc-800 dark:text-zinc-200">
                {attempts}
              </span>
            </div>
            <div className="px-3 py-1.5 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800">
              <span className="text-zinc-500 block text-[10px] uppercase font-medium">
                Self-Healed
              </span>
              <span
                className={`font-semibold flex items-center gap-1 ${
                  healed
                    ? 'text-purple-600 dark:text-purple-400'
                    : 'text-zinc-500'
                }`}
              >
                {healed && <Sparkles className="w-3 h-3" />}
                {healed ? 'Yes' : 'No'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Validation Issues List */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
              Validation Issues
            </h4>
            <span className="px-2 py-0.5 rounded-full bg-zinc-200 dark:bg-zinc-800 text-[11px] font-mono text-zinc-700 dark:text-zinc-300">
              {issues.length}
            </span>
          </div>
        </div>

        {issues.length > 0 ? (
          <div className="space-y-2">
            {issues.map((issue, idx) => {
              const severity = issue?.severity || 'warning'
              return (
                <div
                  key={idx}
                  className="p-3.5 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xs flex items-start justify-between gap-3 text-xs"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-100 bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 rounded text-[11px]">
                        {issue?.field || 'general'}
                      </span>
                      <Badge
                        variant={
                          severity === 'error'
                            ? 'error'
                            : severity === 'warning'
                            ? 'warning'
                            : 'neutral'
                        }
                        className="text-[10px] uppercase tracking-wider py-0 px-1.5"
                      >
                        {severity}
                      </Badge>
                    </div>
                    <p className="text-zinc-600 dark:text-zinc-300 text-xs leading-relaxed">
                      {issue?.message || 'Unspecified validation condition'}
                    </p>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="p-8 text-center rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 text-xs text-zinc-500 flex flex-col items-center gap-2">
            <ShieldCheck className="w-6 h-6 text-emerald-500/80" />
            <span>No validation issues recorded. The extracted fields reconciled cleanly.</span>
          </div>
        )}
      </div>
    </div>
  )
}
