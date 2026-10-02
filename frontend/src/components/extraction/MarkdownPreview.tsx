import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MarkdownPreviewProps {
  markdown: string
}

export const MarkdownPreview: React.FC<MarkdownPreviewProps> = ({ markdown }) => {
  return (
    <div className="w-full h-full p-6 overflow-auto bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 selection:bg-blue-100 dark:selection:bg-blue-900/60">
      <div className="max-w-4xl mx-auto prose dark:prose-invert prose-zinc prose-sm sm:prose-base leading-normal">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ ...props }) => (
              <h1
                className="text-xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50 border-b border-zinc-200 dark:border-zinc-800 pb-2 mb-4 mt-6"
                {...props}
              />
            ),
            h2: ({ ...props }) => (
              <h2
                className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-zinc-100 border-b border-zinc-100 dark:border-zinc-800/60 pb-1 mb-3 mt-5"
                {...props}
              />
            ),
            h3: ({ ...props }) => (
              <h3
                className="text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-100 mb-2 mt-4"
                {...props}
              />
            ),
            p: ({ ...props }) => (
              <p className="text-xs sm:text-sm text-zinc-700 dark:text-zinc-300 leading-relaxed my-2" {...props} />
            ),
            ul: ({ ...props }) => (
              <ul className="list-disc list-inside space-y-1 my-2 text-xs sm:text-sm text-zinc-700 dark:text-zinc-300 pl-2" {...props} />
            ),
            ol: ({ ...props }) => (
              <ol className="list-decimal list-inside space-y-1 my-2 text-xs sm:text-sm text-zinc-700 dark:text-zinc-300 pl-2" {...props} />
            ),
            table: ({ ...props }) => (
              <div className="my-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800 shadow-2xs">
                <table className="w-full text-left text-xs border-collapse divide-y divide-zinc-200 dark:divide-zinc-800" {...props} />
              </div>
            ),
            thead: ({ ...props }) => (
              <thead className="bg-zinc-50 dark:bg-zinc-900 text-zinc-800 dark:text-zinc-200 font-semibold" {...props} />
            ),
            th: ({ ...props }) => (
              <th className="px-3 py-2 font-medium tracking-tight border-r last:border-r-0 border-zinc-200 dark:border-zinc-800" {...props} />
            ),
            td: ({ ...props }) => (
              <td className="px-3 py-2 text-zinc-700 dark:text-zinc-300 border-r last:border-r-0 border-zinc-200 dark:border-zinc-800/80 font-mono text-[11px]" {...props} />
            ),
            tr: ({ ...props }) => (
              <tr className="hover:bg-zinc-50/60 dark:hover:bg-zinc-900/40 transition-colors" {...props} />
            ),
            code: ({ className, children, ...props }) => {
              const isInline = !className
              return isInline ? (
                <code
                  className="px-1.5 py-0.5 rounded font-mono text-[11px] bg-zinc-100 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200"
                  {...props}
                >
                  {children}
                </code>
              ) : (
                <div className="my-3 rounded-lg bg-zinc-900 dark:bg-zinc-900/90 text-zinc-100 p-3 font-mono text-xs overflow-x-auto border border-zinc-800">
                  <code className={className} {...props}>
                    {children}
                  </code>
                </div>
              )
            },
            blockquote: ({ ...props }) => (
              <blockquote
                className="border-l-2 border-zinc-300 dark:border-zinc-700 pl-3 my-2 text-xs italic text-zinc-600 dark:text-zinc-400"
                {...props}
              />
            ),
          }}
        >
          {markdown}
        </ReactMarkdown>
      </div>
    </div>
  )
}
