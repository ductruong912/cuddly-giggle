import { Monitor, Moon, Sun } from 'lucide-react'
import { getMessages } from './i18n'
import type { Language } from './i18n'
import type { Theme } from './preferences'

interface SettingsProps {
  theme: Theme
  language: Language
  setTheme: (value: Theme) => void
  setLanguage: (value: Language) => void
}

export default function Settings({ theme, language, setTheme, setLanguage }: SettingsProps) {
  const t = getMessages(language)
  return (
    <section id="preferences" className="settings-panel" aria-label={t.settings}>
      <fieldset>
        <legend>{t.appearance}</legend>
        <div className="theme-options">
          {(
            [
              { value: 'light', icon: Sun },
              { value: 'dark', icon: Moon },
              { value: 'system', icon: Monitor },
            ] as const
          ).map(({ value, icon: Icon }) => (
            <label key={value} title={t[value]}>
              <input
                type="radio"
                aria-label={t[value]}
                name="theme"
                value={value}
                checked={theme === value}
                onChange={() => setTheme(value)}
              />
              <span aria-hidden="true">
                <Icon size={17} />
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="language-option">
        <label htmlFor="language-select">{t.language}</label>
        <select
          id="language-select"
          value={language}
          onChange={(event) => setLanguage(event.target.value as Language)}
        >
          <option value="vi" lang="vi">
            Tiếng Việt
          </option>
          <option value="en" lang="en">
            English
          </option>
        </select>
      </div>
    </section>
  )
}
