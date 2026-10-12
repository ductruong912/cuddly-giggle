import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import DocumentPreview from './DocumentPreview'
import { ocrFixture } from '../fixtures/ocrFixture'
import type { OCRBlock, OCRPage } from './ocr'
import { useState } from 'react'

function Preview({ result }: { result: ReturnType<typeof ocrFixture> }) {
  const [selected, setSelected] = useState<OCRBlock | null>(null)
  const [showBbox, setShowBbox] = useState(false)
  return (
    <>
      <button onClick={() => setShowBbox(!showBbox)}>Toggle bbox</button>
      <DocumentPreview
        file={new File(['x'], 'scan.png')}
        url="blob:synthetic"
        result={result}
        selected={selected}
        onSelect={setSelected}
        showBbox={showBbox}
        pageIndex={0}
        onPageChange={() => {}}
      />
    </>
  )
}

const block: OCRBlock = {
  block_id: 'bbox-test',
  type: 'text',
  content: 'Synthetic recognized text',
  bbox: [
    { x: 10, y: 20 },
    { x: 100, y: 20 },
    { x: 100, y: 50 },
    { x: 10, y: 50 },
  ],
  confidence: 0.95,
  page_index: 0,
  source_engine: 'test',
  extra: {},
}

describe('OCR bbox preview', () => {
  it('shows processed OCR pixels with linked bbox and allows returning to original', async () => {
    const result = ocrFixture('Synthetic')
    result.blocks = [block]
    result.pages = [
      {
        page_index: 0,
        blocks: [block],
        tables: [],
        reading_order: [block.block_id],
        source_engine: 'test',
        confidence: 0.95,
        geometry: { width: 200, height: 300, coordinate_space: 'processed' },
        preview_image: 'data:image/jpeg;base64,YQ==',
      },
    ]
    const { container } = render(<Preview result={result} />)
    await userEvent.click(screen.getByRole('button', { name: 'Toggle bbox' }))
    expect(screen.getByRole('img', { name: 'Ảnh OCR' })).toHaveAttribute(
      'src',
      result.pages[0].preview_image,
    )
    expect(screen.getByRole('button', { name: 'Vùng 1 · text' })).toBeVisible()
    await userEvent.hover(screen.getByRole('button', { name: 'Vùng 1 · text' }))
    expect(screen.getByRole('button', { name: 'Vùng 1 · text' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.queryByRole('button', { name: 'Bản gốc' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ảnh OCR' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Toggle bbox' }))
    expect(container.querySelector('.bbox-overlay')).toBeNull()
    expect(container.querySelector('img')).toHaveAttribute('src', 'blob:synthetic')
    await userEvent.click(screen.getByRole('button', { name: 'Toggle bbox' }))
    await userEvent.click(screen.getByRole('button', { name: 'Phóng to' }))
    expect(container.querySelector('.bbox-stage')).toHaveStyle({ width: '125%' })
  })

  it('maps rotated bbox to original while leaving OCR coordinates intact', async () => {
    const result = ocrFixture('Synthetic')
    result.blocks = [block]
    result.pages = [
      {
        page_index: 0,
        blocks: [block],
        tables: [],
        reading_order: [block.block_id],
        source_engine: 'test',
        confidence: 0.95,
        geometry: {
          width: 300,
          height: 200,
          coordinate_space: 'processed',
          original: { width: 200, height: 300, transform: [0, -1, 200, 1, 0, 0] },
        },
      },
    ]
    const { container } = render(<Preview result={result} />)
    await userEvent.click(screen.getByRole('button', { name: 'Toggle bbox' }))
    expect(screen.getByRole('button', { name: 'Vùng 1 · text' })).toHaveAttribute(
      'points',
      '180,10 180,100 150,100 150,10',
    )
    expect(container.querySelector('svg.bbox-overlay')).toHaveAttribute('viewBox', '0 0 200 300')
    expect(block.bbox[0]).toEqual({ x: 10, y: 20 })
  })

  it('does not fetch external OCR preview URLs', async () => {
    const result = ocrFixture('Synthetic')
    result.blocks = [block]
    result.pages = [
      {
        page_index: 0,
        blocks: [block],
        tables: [],
        reading_order: [],
        source_engine: 'test',
        confidence: 0,
        geometry: { width: 200, height: 300, coordinate_space: 'processed' },
        preview_image: 'https://example.com/private-scan.jpg',
      },
    ]
    const { container } = render(<Preview result={result} />)
    await userEvent.click(screen.getByRole('button', { name: 'Toggle bbox' }))
    expect(container.querySelector('img')).toHaveAttribute('src', 'blob:synthetic')
    expect(screen.queryByRole('button', { name: 'Ảnh OCR' })).not.toBeInTheDocument()
  })
  it.each(['original', 'processed', 'unknown'])(
    'only overlays known original coordinates: %s',
    async (space) => {
      const result = ocrFixture('Synthetic')
      const page: OCRPage = {
        page_index: 0,
        blocks: [block],
        tables: [],
        reading_order: [block.block_id],
        source_engine: 'test',
        confidence: 0.95,
        geometry: space === 'unknown' ? null : { width: 200, height: 300, coordinate_space: space },
      }
      result.blocks = [block]
      result.pages = [page]
      const { container } = render(<Preview result={result} />)
      expect(container.querySelector('.bbox-overlay')).toBeNull()
      await userEvent.click(screen.getByRole('button', { name: 'Toggle bbox' }))
      if (space !== 'original') {
        expect(container.querySelector('.bbox-overlay')).toBeNull()
        expect(screen.getByText(/chưa có bbox khớp/)).toBeVisible()
        return
      }
      const polygon = screen.getByRole('button', { name: 'Vùng 1 · text' })
      expect(polygon).toHaveAttribute('points', '10,20 100,20 100,50 10,50')
      polygon.focus()
      await userEvent.keyboard('{Enter}')
      expect(polygon).toHaveAttribute('aria-pressed', 'true')
      await userEvent.click(screen.getByRole('button', { name: 'Phóng to' }))
      expect(container.querySelector('.bbox-stage')).toHaveStyle({ width: '125%' })
      await userEvent.click(screen.getByRole('button', { name: 'Toggle bbox' }))
      expect(container.querySelector('.bbox-overlay')).toBeNull()
    },
  )
})
