import React from 'react'
import { cn } from '@/lib/utils'

export type BadgeVariant =
  | 'default'
  | 'success'
  | 'warning'
  | 'error'
  | 'neutral'
  | 'outline'

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant
  children: React.ReactNode
}

export const Badge: React.FC<BadgeProps> = ({
  variant = 'default',
  className,
  children,
  ...props
}) => {
  const variantStyles: Record<BadgeVariant, string> = {
    default:
      'bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200 border-zinc-200 dark:border-zinc-700',
    success:
      'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
    warning:
      'bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border-amber-200 dark:border-amber-800',
    error:
      'bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300 border-rose-200 dark:border-rose-800',
    neutral:
      'bg-zinc-50 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400 border-zinc-200 dark:border-zinc-800',
    outline:
      'bg-transparent text-zinc-700 dark:text-zinc-300 border-zinc-300 dark:border-zinc-700',
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded-md border tracking-tight transition-colors',
        variantStyles[variant],
        className
      )}
      {...props}
    >
      {children}
    </span>
  )
}
