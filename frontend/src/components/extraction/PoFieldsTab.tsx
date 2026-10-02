import React from 'react'
import { Calendar, Hash, Layers, CheckCircle2, AlertTriangle } from 'lucide-react'
import { Badge } from '@/components/common/Badge'
import type { LLMExtractionResponse } from '@/types/api'

interface PoFieldsTabProps {
  response: LLMExtractionResponse
}

export const PoFieldsTab: React.FC<PoFieldsTabProps> = ({ response }) => {
  const data = response?.data
  const ocr = response?.ocr
  const validation = response?.validation
  const items = Array.isArray(data?.items) ? data.items : []

  // Calculate sum of line items safely without NaN or crash
  const totalAmount = items.reduce((sum, item) => {
    if (!item) return sum
    if (typeof item.extension === 'number' && !isNaN(item.extension)) {
      return sum + item.extension
    }
    const q = typeof item.quantity === 'number' && !isNaN(item.quantity) ? item.quantity : 0
    const p = typeof item.unit_price === 'number' && !isNaN(item.unit_price) ? item.unit_price : 0
    return sum + q * p
  }, 0)

  const validationStatus = validation?.status === 'valid' ? 'valid' : 'needs_review'
  const isValid = validationStatus === 'valid'
  const pageCount = typeof ocr?.page_count === 'number' ? ocr.page_count : 1

  return (
    <div className="w-full h-full p-6 overflow-auto bg-zinc-50/40 dark:bg-zinc-950 space-y-6">
      {/* Header Cards Grid */}
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">
          Purchase Order Summary
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {/* PO Number */}
          <div className="p-3 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xs">
            <div className="flex items-center gap-1.5 text-zinc-500 text-xs mb-1">
              <Hash className="w-3.5 h-3.5" />
              <span>PO Number</span>
            </div>
            <div className="font-mono text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
              {data?.po_number || (
                <span className="text-zinc-400 italic font-sans font-normal text-xs">
                  Not found
                </span>
              )}
            </div>
          </div>

          {/* PO Date */}
          <div className="p-3 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xs">
            <div className="flex items-center gap-1.5 text-zinc-500 text-xs mb-1">
              <Calendar className="w-3.5 h-3.5" />
              <span>PO Date</span>
            </div>
            <div className="font-mono text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
              {data?.po_date || (
                <span className="text-zinc-400 italic font-sans font-normal text-xs">
                  Not found
                </span>
              )}
            </div>
          </div>

          {/* Page Count */}
          <div className="p-3 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xs">
            <div className="flex items-center gap-1.5 text-zinc-500 text-xs mb-1">
              <Layers className="w-3.5 h-3.5" />
              <span>Pages</span>
            </div>
            <div className="font-mono text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {pageCount} {pageCount === 1 ? 'page' : 'pages'}
            </div>
          </div>

          {/* Validation Status */}
          <div className="p-3 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xs">
            <div className="text-zinc-500 text-xs mb-1">Validation</div>
            <div>
              <Badge
                variant={isValid ? 'success' : 'warning'}
                className="text-xs"
              >
                {isValid ? (
                  <>
                    <CheckCircle2 className="w-3 h-3" />
                    <span>valid</span>
                  </>
                ) : (
                  <>
                    <AlertTriangle className="w-3 h-3" />
                    <span>needs_review</span>
                  </>
                )}
              </Badge>
            </div>
          </div>
        </div>
      </div>

      {/* Line Items Table */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
              Line Items
            </h4>
            <span className="px-2 py-0.5 rounded-full bg-zinc-200 dark:bg-zinc-800 text-[11px] font-mono text-zinc-700 dark:text-zinc-300">
              {items.length}
            </span>
          </div>

          {items.length > 0 && (
            <div className="text-xs text-zinc-500">
              Computed total:{' '}
              <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                {totalAmount.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
            </div>
          )}
        </div>

        {items.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/80 dark:bg-zinc-800/50 text-zinc-600 dark:text-zinc-400 font-semibold select-none">
                  <th className="py-2.5 px-3 w-10 text-center font-mono text-[11px]">#</th>
                  <th className="py-2.5 px-3">TOTO Number</th>
                  <th className="py-2.5 px-3">Customer Number</th>
                  <th className="py-2.5 px-3 text-right">Quantity</th>
                  <th className="py-2.5 px-3 text-right">Unit Price</th>
                  <th className="py-2.5 px-3 text-right">Extension</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/80 font-mono text-[11px]">
                {items.map((item, idx) => (
                  <tr
                    key={idx}
                    className="hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 transition-colors"
                  >
                    <td className="py-2 px-3 text-center text-zinc-400 font-mono text-[10px]">
                      {idx + 1}
                    </td>
                    <td className="py-2 px-3 font-medium text-zinc-900 dark:text-zinc-100">
                      {item?.toto_number || '—'}
                    </td>
                    <td className="py-2 px-3 text-zinc-500 dark:text-zinc-400">
                      {item?.customer_number || '—'}
                    </td>
                    <td className="py-2 px-3 text-right text-zinc-800 dark:text-zinc-200">
                      {typeof item?.quantity === 'number' && !isNaN(item.quantity)
                        ? item.quantity.toLocaleString()
                        : '—'}
                    </td>
                    <td className="py-2 px-3 text-right text-zinc-800 dark:text-zinc-200">
                      {typeof item?.unit_price === 'number' && !isNaN(item.unit_price)
                        ? item.unit_price.toLocaleString(undefined, {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                          })
                        : '—'}
                    </td>
                    <td className="py-2 px-3 text-right font-semibold text-zinc-900 dark:text-zinc-100">
                      {typeof item?.extension === 'number' && !isNaN(item.extension)
                        ? item.extension.toLocaleString(undefined, {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                          })
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center rounded-lg border border-dashed border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/50 text-xs text-zinc-400">
            No line items extracted from document.
          </div>
        )}
      </div>
    </div>
  )
}
