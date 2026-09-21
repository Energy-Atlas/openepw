import { useEffect, useState } from 'react'
import { run } from '../app/actions'
import { useApp } from '../app/store'
import { CHROME_VARIABLES, resolveAppearance, type AppearancePreference } from './appearances'

/** Applies the stored appearance; changes go through the shared setAppearance action. */
export function useTheme() {
  const preference = useApp((state) => state.appearance)
  const setPreference = (appearance: AppearancePreference) =>
    run({ type: 'setAppearance', appearance })
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
  }, [appearance])
  return { preference, setPreference, appearance }
}
