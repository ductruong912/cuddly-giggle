import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize from 'rehype-sanitize'
import { getMessages } from './i18n'
import type { Language } from './i18n'

export default function MarkdownResult({
  markdown,
  language = 'vi',
}: {
  markdown: string
  language?: Language
}) {
  const t = getMessages(language)
  return (
    <article className="markdown-content" aria-label={t.renderedResult}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, rehypeSanitize]}
        components={{
          // OCR output is untrusted: do not fetch referenced images or create live links.
          img: ({ alt }) => (
            <span className="omitted-image">
              [{t.image}
              {alt ? `: ${alt}` : ''}]
            </span>
          ),
          a: ({ children }) => <span className="document-link">{children}</span>,
        }}
      >
        {markdown}
      </Markdown>
    </article>
  )
}
