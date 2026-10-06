import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize from 'rehype-sanitize'

export default function MarkdownResult({ markdown }: { markdown: string }) {
  return (
    <article className="markdown-content" aria-label="Kết quả trình bày">
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, rehypeSanitize]}
        components={{
          // OCR output is untrusted: do not fetch referenced images or create live links.
          img: ({ alt }) => <span className="omitted-image">[Ảnh{alt ? `: ${alt}` : ''}]</span>,
          a: ({ children }) => <span className="document-link">{children}</span>,
        }}
      >
        {markdown}
      </Markdown>
    </article>
  )
}
