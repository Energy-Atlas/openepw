const storageKey = 'openepw.intents.v1'
function read(): Record<string, string> {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(storageKey) || '{}')
    return v && typeof v === 'object' && !Array.isArray(v)
      ? Object.fromEntries(
          Object.entries(v).filter(
            ([k, val]) => k.length <= 128 && typeof val === 'string' && val.length <= 128,
          ),
        )
      : {}
  } catch {
    return {}
  }
}
export function rememberedIntent(hash: string) {
  return read()[hash]
}
export function rememberIntent(hash: string, key: string) {
  try {
    localStorage.setItem(
      storageKey,
      JSON.stringify(
        Object.fromEntries(
          [...Object.entries(read()).filter(([h]) => h !== hash), [hash, key]].slice(-100),
        ),
      ),
    )
  } catch {
    /* Storage may be disabled; same-session safety still applies. */
  }
}
