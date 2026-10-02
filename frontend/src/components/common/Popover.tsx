import React, { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

interface PopoverProps {
  trigger: React.ReactNode
  content: React.ReactNode
  align?: 'left' | 'right'
  className?: string
}

export const Popover: React.FC<PopoverProps> = ({
  trigger,
  content,
  align = 'right',
  className,
}) => {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false)
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  return (
    <div className="relative inline-block text-left" ref={containerRef}>
      <div onClick={() => setIsOpen((prev) => !prev)} className="cursor-pointer">
        {trigger}
      </div>

      {isOpen && (
        <div
          className={cn(
            'absolute z-50 mt-2 w-72 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 p-3 shadow-lg animate-in fade-in zoom-in-95 duration-150',
            align === 'right' ? 'right-0' : 'left-0',
            className
          )}
        >
          {content}
        </div>
      )}
    </div>
  )
}
