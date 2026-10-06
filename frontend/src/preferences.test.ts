import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { readPreferences, usePreferences } from './preferences'

describe('display preferences', () => {
  it.each(['{broken', '{"theme":"unknown","language":"de"}', 'null'])(
    'ignores invalid stored preferences: %s',
    (saved) => {
      localStorage.setItem('cuddly-giggle.preferences.v1', saved)
      expect(readPreferences()).toEqual({ theme: 'system', language: 'vi' })
    },
  )

  it('tracks system theme changes, respects an explicit choice and saves language', () => {
    const media = Object.assign(new EventTarget(), { matches: false })
    const removeListener = vi.spyOn(media, 'removeEventListener')
    vi.stubGlobal('matchMedia', () => media)
    const { result, unmount } = renderHook(usePreferences)
    expect(document.documentElement.dataset.theme).toBe('light')
    act(() => {
      media.matches = true
      media.dispatchEvent(new Event('change'))
    })
    expect(document.documentElement.dataset.theme).toBe('dark')
    act(() => result.current.setTheme('light'))
    act(() => {
      media.matches = true
      media.dispatchEvent(new Event('change'))
    })
    expect(document.documentElement.dataset.theme).toBe('light')
    act(() => result.current.setLanguage('en'))
    expect(document.documentElement.lang).toBe('en')
    expect(readPreferences()).toEqual({ theme: 'light', language: 'en' })
    act(() => result.current.setTheme('system'))
    expect(document.documentElement.dataset.theme).toBe('dark')
    unmount()
    expect(removeListener).toHaveBeenCalled()
  })

  it('remains usable when local storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const { result } = renderHook(usePreferences)
    act(() => result.current.setTheme('dark'))
    act(() => result.current.setLanguage('en'))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.lang).toBe('en')
  })
})
