import { useEffect, useState } from 'react'
import {
  CHROME_VARIABLES,
  resolveAppearance,
  isAppearanceId,
  type AppearancePreference,
} from './appearances'
export function useTheme() {
  const [preference, setPreference] = useState<AppearancePreference>(() => {
    const p = localStorage.getItem('openepw.appearance.v1')
    return p && isAppearanceId(p) ? p : 'system'
  })
  const [dark, setDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches)
  useEffect(() => {
    const q = matchMedia('(prefers-color-scheme: dark)')
    const fn = () => setDark(q.matches)
    q.addEventListener('change', fn)
    return () => q.removeEventListener('change', fn)
  }, [])
  const appearance = resolveAppearance(preference, dark)
  useEffect(() => {
    for (const [key, css] of Object.entries(CHROME_VARIABLES))
      document.documentElement.style.setProperty(
        css,
        appearance.chrome[key as keyof typeof appearance.chrome],
      )
    document.documentElement.style.colorScheme = appearance.scheme
    localStorage.setItem('openepw.appearance.v1', preference)
  }, [appearance, preference])
  return { preference, setPreference, appearance }
}
