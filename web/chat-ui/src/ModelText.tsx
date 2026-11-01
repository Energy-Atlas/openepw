import Markdown from 'react-markdown'

/**
 * Text written by the model or the host, as Markdown. Raw HTML is shown as text, never rendered;
 * unsafe link protocols are removed (react-markdown's default URL transform) and the host's link
 * policy has already run; links open in a new tab without access to this page.
 */
export function ModelText({ text }: { text: string }) {
  return <div className="md"><Markdown components={{
    a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
    img: ({ alt }) => <span>{alt}</span>,
  }}>{text}</Markdown></div>
}
