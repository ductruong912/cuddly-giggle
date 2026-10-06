import { useEffect, useMemo, useRef } from 'react'
import type { OCRBlock, OCRResult } from './ocr'
import { blockKey } from './ocr'
import type { Language } from './i18n'
import { getMessages } from './i18n'
import MarkdownResult from './MarkdownResult'

export default function OCRBlocks({
  result,
  selected,
  onSelect,
  scrollSelected,
  language,
}: {
  result: OCRResult | null
  selected: OCRBlock | null
  onSelect: (block: OCRBlock) => void
  scrollSelected: boolean
  language: Language
}) {
  const t = getMessages(language)
  const nodes = useRef(new Map<string, HTMLElement>())
  const blocks = useMemo(() => {
    if (!result) return []
    if (!result.pages.length) return result.blocks
    return [...result.pages]
      .sort((a, b) => a.page_index - b.page_index)
      .flatMap((page) => {
        const order = new Map(page.reading_order.map((id, index) => [id, index]))
        return [...page.blocks].sort(
          (a, b) => (order.get(a.block_id) ?? Infinity) - (order.get(b.block_id) ?? Infinity),
        )
      })
  }, [result])
  const selectedKey = selected ? blockKey(selected) : null
  useEffect(() => {
    if (scrollSelected && selectedKey)
      nodes.current.get(selectedKey)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [selectedKey, scrollSelected])
  if (!blocks.length) return <p className="ocr-notice">{t.noBlocks}</p>
  return (
    <div className="ocr-blocks">
      {blocks.map((block, index) => {
        const key = blockKey(block)
        return (
          <article
            key={key}
            data-block-type={block.type}
            className={`ocr-block ${key === selectedKey ? 'selected' : ''}`}
            ref={(node) => {
              if (node) nodes.current.set(key, node)
              else nodes.current.delete(key)
            }}
            role="button"
            tabIndex={0}
            aria-label={t.contentBlockLabel(index + 1, block.type, block.page_index + 1)}
            aria-pressed={key === selectedKey}
            onMouseEnter={() => onSelect(block)}
            onFocus={() => onSelect(block)}
            onClick={() => onSelect(block)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onSelect(block)
              }
            }}
          >
            <div className="ocr-block-meta">
              <strong>
                {(typeof block.extra.label === 'string' && block.extra.label.trim()
                  ? block.extra.label
                  : block.type
                ).toUpperCase()}
              </strong>
              <span>{t.blockPage(block.page_index + 1)}</span>
              <span title={t.confidenceScore}>{block.confidence.toFixed(3)}</span>
            </div>
            <div className="ocr-block-content">
              {block.type === 'title' ? (
                <h3>{block.content || '—'}</h3>
              ) : (
                <MarkdownResult markdown={block.content || '—'} language={language} />
              )}
            </div>
          </article>
        )
      })}
    </div>
  )
}
