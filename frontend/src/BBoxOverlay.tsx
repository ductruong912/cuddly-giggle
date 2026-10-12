import type { OCRBlock, OCRPage } from './ocr'
import { canOverlay } from './ocr'
import { useEffect, useRef } from 'react'
import type { Language } from './i18n'
import { getMessages } from './i18n'

export default function BBoxOverlay({
  page,
  selected,
  onSelect,
  language,
  scrollSelected = false,
  space = 'original',
}: {
  page: OCRPage | undefined
  selected: OCRBlock | null
  onSelect: (block: OCRBlock) => void
  language: Language
  scrollSelected?: boolean
  space?: 'original' | 'processed'
}) {
  const activeNode = useRef<SVGPolygonElement | null>(null)
  const selectedId = selected?.block_id
  const selectedPage = selected?.page_index
  useEffect(() => {
    if (scrollSelected) activeNode.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [selectedId, selectedPage, scrollSelected])
  if (!canOverlay(page, space)) return null
  const geometry =
    space === 'original' ? (page.geometry!.original ?? page.geometry!) : page.geometry!
  const transform = space === 'original' ? page.geometry!.original?.transform : null
  const t = getMessages(language)
  return (
    <svg
      className="bbox-overlay"
      viewBox={`0 0 ${geometry.width} ${geometry.height}`}
      preserveAspectRatio="none"
      aria-label={t.bboxBlocks}
    >
      {page.blocks
        .filter((block) => block.bbox.length >= 3)
        .map((block, index) => (
          <polygon
            key={block.block_id}
            data-block-type={block.type}
            ref={
              selected?.block_id === block.block_id && selected.page_index === block.page_index
                ? activeNode
                : undefined
            }
            points={block.bbox
              .map((p) => {
                if (!transform) return `${p.x},${p.y}`
                const [a, b, c, d, e, f] = transform
                return `${a * p.x + b * p.y + c},${d * p.x + e * p.y + f}`
              })
              .join(' ')}
            className={
              selected?.block_id === block.block_id && selected.page_index === block.page_index
                ? 'selected'
                : ''
            }
            vectorEffect="non-scaling-stroke"
            role="button"
            tabIndex={0}
            aria-label={t.blockLabel(index + 1, block.type)}
            aria-pressed={
              selected?.block_id === block.block_id && selected.page_index === block.page_index
            }
            onClick={() => onSelect(block)}
            onMouseEnter={() => onSelect(block)}
            onFocus={() => onSelect(block)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onSelect(block)
              }
            }}
          >
            <title>{block.content || block.type}</title>
          </polygon>
        ))}
    </svg>
  )
}
