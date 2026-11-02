import { Fragment, useEffect, useState, type FormEvent } from 'react'
import { ModelText } from './ModelText'
import { ProductDialog, type ProductOption } from './ProductDialog'
import { EnterIcon, TickIcon } from './icons'
import type { AgentAnswer, AgentForm, AgentSnapshot } from './types'

export type AnswerFields = Omit<AgentAnswer, 'interaction_id' | 'revision'>

const STATUS_WORDS: Record<string, string> = { empty: 'not set', proposed: 'to confirm', confirmed: 'confirmed',
  recheck: 'choose again' }

/**
 * The open form of an agent session, rendered by kind, and the reply area under it. Text is
 * free whenever the form takes text; forms with actions show their buttons until the person
 * chooses to type instead. Run, approvals and choices are only ever sent as form answers.
 */
export function FormDock({ snapshot, busy, checked, pendingChoice, onPendingChoice, onToggleProduct,
  onAnswer, onText, onUpload }: {
  snapshot: AgentSnapshot
  busy: boolean
  checked: string[]
  pendingChoice: string | null
  onPendingChoice: (id: string | null) => void
  onToggleProduct: (id: string) => void
  onAnswer: (fields: AnswerFields) => void
  onText: (text: string) => void
  onUpload: (file: File) => void
}) {
  const form = snapshot.form
  const [typing, setTyping] = useState(false)
  const [message, setMessage] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  useEffect(() => { setTyping(false); setPicked([]) }, [form?.id, form?.revision])
  useEffect(() => { if (typing) document.getElementById('chat-message')?.focus() }, [typing])

  const kind = form?.kind
  const textReply = !form || typing || kind === 'text' || kind === 'map_input' || kind === 'location_review'
    || kind === 'upload'
  const send = (event: FormEvent) => {
    event.preventDefault()
    const text = message.trim()
    if (!text || busy) return
    setMessage('')
    onText(text)
  }
  const changes = (form?.options ?? []).filter(option => option.id.startsWith('change:'))
  const backLabel = kind === 'choice' || kind === 'product_choice' ? 'Back to options'
    : kind === 'plan_review' || kind === 'request_summary' ? 'Back to review' : null
  const places = kind === 'choice' && snapshot.candidates.length > 0
  const offers: ProductOption[] = kind === 'product_choice'
    ? (snapshot.offers.length ? snapshot.offers.map(offer => ({ ...offer, detail: offer.detail ?? undefined,
      available: offer.available ?? undefined, sites: offer.sites ?? undefined }))
      : (form?.options ?? []).map(option => ({ id: option.id, label: option.label, detail: option.detail ?? undefined })))
    : []

  return <>
    {form && <section className="action-card" aria-label="Current question">
      <span className="event-kind">{snapshot.mode === 'agent' ? 'Agent' : 'Guided'}</span>
      <h2>{form.prompt}</h2>
      {form.summary && kind !== 'request_summary' && <FormSummary form={form} />}
      {(kind === 'request_summary' || (kind === 'plan_review' && Array.isArray(form.data?.parts))) &&
        <RequestParts snapshot={snapshot} form={form} />}
    </section>}
    {busy && <p className="dock-status" role="status" aria-label="Working">Working…</p>}
    {snapshot.ended ? null : <form className="composer" onSubmit={send} aria-label="Reply">
      {/* The product dialog is its own panel: reply-options pill styles would reach its info buttons. */}
      {!textReply && !busy && kind === 'product_choice' && <ProductDialog options={offers} selected={checked} busy={busy}
        onToggle={onToggleProduct} onType={() => setTyping(true)} onConfirm={() => onAnswer({ choice_ids: checked })} />}
      {!textReply && !busy && kind !== 'product_choice' && <div className="reply-options" role="group" aria-label="Reply options">
        {kind === 'choice' && <>
          {form!.options.map((option, index) => places
            ? <span className="option-row" key={option.id}>
              <button type="button" className="numbered-option" disabled={busy}
                aria-pressed={pendingChoice === option.id} onClick={() => onPendingChoice(option.id)}>
                <span className="option-number" aria-hidden="true">{index + 1}</span>
                {option.label}{option.detail && <span className="option-detail">{option.detail}</span>}</button>
              {pendingChoice === option.id && <button className="option-tick" type="button" disabled={busy}
                aria-label="Confirm" title="Confirm" onClick={() => onAnswer({ choice_ids: [option.id] })}><TickIcon /></button>}
            </span>
            : form!.multi
              ? <label key={option.id} className="product-row"><input type="checkbox" checked={picked.includes(option.id)}
                onChange={() => setPicked(current => current.includes(option.id)
                  ? current.filter(item => item !== option.id) : [...current, option.id])} /> {option.label}
                {option.detail && <span className="option-detail">{option.detail}</span>}</label>
              : <button key={option.id} disabled={busy} type="button" onClick={() => onAnswer({ choice_ids: [option.id] })}>
                {option.label}{option.detail && <span className="option-detail">{option.detail}</span>}</button>)}
          {form!.multi && !places && <button className="reply-primary" type="button" disabled={!picked.length}
            onClick={() => onAnswer({ choice_ids: picked })}><TickIcon />Confirm</button>}
          {form!.allow_text && <button className="reply-alt" type="button" onClick={() => setTyping(true)}>Other — type an answer</button>}
        </>}
        {kind === 'plan_review' && <>
          <button className="reply-primary" type="button" onClick={() => onAnswer({ approve: true })}>
            <TickIcon />Run reviewed plan</button>
          <ChangeButtons changes={changes} onAnswer={onAnswer} />
          <button className="reply-alt" type="button" onClick={() => setTyping(true)}>Type a correction</button>
        </>}
        {kind === 'request_summary' && <>
          <button className="reply-primary" type="button" onClick={() => onAnswer({ approve: true })}>
            <TickIcon />Confirm request</button>
          <ChangeButtons changes={changes} onAnswer={onAnswer} />
          <button className="reply-alt" type="button" onClick={() => setTyping(true)}>Type a correction</button>
        </>}
      </div>}
      {textReply && <>
        {kind === 'location_review' && !busy && <button className="reply-primary approve-location" type="button"
          onClick={() => onAnswer({ approve: true })}>
          <TickIcon />{form!.data?.several ? 'Approve locations' : 'Approve location'}</button>}
        {kind === 'upload' && !busy && <label className="upload-control">
          <span>Choose an EPW file</span>
          <input type="file" aria-label="EPW file" accept=".epw,text/plain" onChange={event => {
            const file = event.target.files?.[0]
            if (file) onUpload(file)
            event.target.value = ''
          }} /></label>}
        <label className="visually-hidden" htmlFor="chat-message">Message</label>
        <div className="composer-row">
          <input id="chat-message" name="message" placeholder={placeholderFor(form, typing)}
            value={message} onChange={event => setMessage(event.target.value)} />
          {typing && (kind === 'choice' || kind === 'product_choice')
            ? <button type="submit" className="icon-submit" aria-label="Confirm" title="Confirm" disabled={busy}><TickIcon /></button>
            : <button type="submit" className="icon-submit" aria-label="Send" title="Send" disabled={busy}><EnterIcon /></button>}
        </div>
        {typing && backLabel && <button className="reply-alt" type="button" onClick={() => setTyping(false)}>{backLabel}</button>}
      </>}
    </form>}
  </>
}

function FormSummary({ form }: { form: AgentForm }) {
  // Summaries are host text (place names already cleaned). A plan review's text ends with the
  // request as lines for text renderers; here the parts list under it shows the request instead.
  let lines = form.summary.split('\n')
  const request = lines.indexOf('Your request:')
  if (form.kind === 'plan_review' && Array.isArray(form.data?.parts) && request >= 0) lines = lines.slice(0, request)
  return <div className="form-summary">{lines.map((line, index) =>
    <Fragment key={index}>{line.startsWith('Warning:') ? <p className="warning">{line}</p>
      : <ModelText text={line} />}</Fragment>)}</div>
}

function RequestParts({ snapshot, form }: { snapshot: AgentSnapshot; form: AgentForm }) {
  const parts = (form.data?.parts as AgentSnapshot['parts'] | undefined) ?? snapshot.parts
  return <dl className="request-parts">{parts.map(part => <div key={part.part} className={`request-part status-${part.status}`}>
    <dt>{part.label}</dt>
    <dd>{part.value}<span className="part-status">{STATUS_WORDS[part.status] ?? part.status}
      {part.origin && part.status !== 'empty' ? ` · ${part.origin}` : ''}</span></dd>
  </div>)}</dl>
}

function ChangeButtons({ changes, onAnswer }: { changes: AgentForm['options']; onAnswer: (fields: AnswerFields) => void }) {
  if (!changes.length) return null
  return <span className="change-actions" role="group" aria-label="Change one part">
    {changes.map(option => <button key={option.id} type="button" className="reply-alt"
      onClick={() => onAnswer({ choice_ids: [option.id] })}>{option.label}</button>)}
  </span>
}

export function placeholderFor(form: AgentForm | null, typing: boolean): string {
  if (!form) return 'Place, years, and weather type'
  const hint = typeof form.data?.hint === 'string' ? form.data.hint : ''
  if (form.kind === 'text' || form.kind === 'map_input') return hint || 'Type your answer'
  if (form.kind === 'location_review') return form.data?.several ? 'Or edit the list, e.g. remove 3' : 'Or describe a correction'
  if (form.kind === 'plan_review' || form.kind === 'request_summary') return 'Describe what to change'
  if (typing) return 'Type another answer'
  return 'Type your answer'
}
