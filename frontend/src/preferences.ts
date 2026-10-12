import { useEffect, useState } from 'react'
import type { Language } from './i18n'

export type Theme = 'light' | 'dark' | 'system'
interface Preferences {
  theme: Theme
  language: Language
}
const storageKey = 'cuddly-giggle.preferences.v1'

export function readPreferences(): Preferences {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? '{}')
    return {
      theme: ['light', 'dark', 'system'].includes(saved?.theme) ? saved.theme : 'system',
      language: saved?.language === 'en' ? 'en' : 'vi',
    }
  } catch {
    return { theme: 'system', language: 'vi' }
  }
}

export function applyPreferences(preferences: Preferences) {
  const dark =
    preferences.theme === 'dark' ||
    (preferences.theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  document.documentElement.lang = preferences.language
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', dark ? '#191f1c' : '#f5f6f2')
}

export function usePreferences() {
  const [preferences, setPreferences] = useState(readPreferences)
  useEffect(() => {
    applyPreferences(preferences)
    try {
      localStorage.setItem(storageKey, JSON.stringify(preferences))
    } catch {
      /* The settings still work when browser storage is unavailable. */
    }
    if (preferences.theme !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const update = () => applyPreferences(preferences)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [preferences])
  return {
    ...preferences,
    setTheme: (theme: Theme) => setPreferences((value) => ({ ...value, theme })),
    setLanguage: (language: Language) => setPreferences((value) => ({ ...value, language })),
  }
}
