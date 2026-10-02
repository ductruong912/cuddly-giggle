import React from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg' | 'icon'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  icon?: React.ReactNode
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'secondary',
      size = 'md',
      loading = false,
      icon,
      className,
      children,
      disabled,
      ...props
    },
    ref
  ) => {
    const baseStyles =
      'inline-flex items-center justify-center font-medium transition-all select-none rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400 focus-visible:ring-offset-1 disabled:opacity-50 disabled:pointer-events-none active:scale-[0.98]'

    const variantStyles: Record<ButtonVariant, string> = {
      primary:
        'bg-zinc-900 text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white shadow-xs',
      secondary:
        'bg-zinc-100 text-zinc-900 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700 border border-zinc-200 dark:border-zinc-700/80',
      outline:
        'bg-transparent border border-zinc-200 hover:bg-zinc-100 text-zinc-900 dark:border-zinc-700 dark:hover:bg-zinc-800/80 dark:text-zinc-100',
      ghost:
        'bg-transparent hover:bg-zinc-100 text-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800',
      danger:
        'bg-rose-600 text-white hover:bg-rose-700 dark:bg-rose-600 dark:hover:bg-rose-500 shadow-xs',
    }

    const sizeStyles: Record<ButtonSize, string> = {
      sm: 'h-8 px-2.5 text-xs gap-1.5',
      md: 'h-9 px-3.5 text-sm gap-2',
      lg: 'h-10 px-4 text-base gap-2.5',
      icon: 'h-8 w-8 p-0 text-sm',
    }

    return (
      <button
        ref={ref}
        className={cn(baseStyles, variantStyles[variant], sizeStyles[size], className)}
        disabled={disabled || loading}
        {...props}
      >
        {loading ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          icon && <span className="shrink-0">{icon}</span>
        )}
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'
