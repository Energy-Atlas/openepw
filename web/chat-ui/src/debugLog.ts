// The "Copy log" text of a testing deployment: what a tester pastes into a bug report.
import type { ApiCall } from './api'
import type { Diagnostics, SessionSnapshot } from './types'

const MAX_SESSION_CHARS = 300_000

export function debugLogText(session: SessionSnapshot | null, calls: readonly ApiCall[],
  server: Diagnostics | null, now = new Date()): string {
  const lines = [`OpenEPW log · copied ${now.toISOString()}`,
    `Page: ${window.location.origin}${window.location.pathname}`,
    `Browser: ${navigator.userAgent}`,
    server ? `Server: ${server.version} · ${server.server_time} · security profile ${server.security_profile ?? 'none'}`
      + ` · catalog ${server.catalog_generation ?? 'none'}`
      + (server.memory ? ` · memory ${server.memory.resident_mb ?? '?'} MB (peak ${server.memory.peak_resident_mb ?? '?'} MB)` : '')
      : 'Server: diagnostics unavailable',
    `Session: ${session ? `${session.id} · revision ${session.revision}` : 'none'}`,
    '', '== Requests (this page, oldest first) ==']
  for (const call of calls) {
    lines.push(`${call.time} ${call.method} ${call.path} → ${call.status ?? 'no response'} (${call.ms} ms)`
      + (call.code || call.message ? ` ${call.code ?? ''}${call.message ? `: ${call.message}` : ''}` : ''))
    if (call.body && (call.status === null || call.status >= 400)) lines.push(`  body: ${call.body}`)
  }
  lines.push('', '== Server warnings and errors (redacted) ==')
  if (!server?.server_log.length) lines.push('none')
  for (const record of server?.server_log ?? [])
    lines.push(`${record.time} ${record.level} ${record.logger}: ${record.message}`)
  let state = JSON.stringify(session, null, 1) ?? 'null'
  if (state.length > MAX_SESSION_CHARS) state = `${state.slice(0, MAX_SESSION_CHARS)}\n… truncated`
  lines.push('', '== Session state ==', state)
  return lines.join('\n')
}

/** Copies the text, or saves it as a file where the clipboard is not available. */
export async function copyOrSave(text: string, filename: string): Promise<'copied' | 'saved'> {
  try {
    await navigator.clipboard.writeText(text)
    return 'copied'
  } catch {
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
    link.download = filename
    link.click()
    URL.revokeObjectURL(link.href)
    return 'saved'
  }
}
