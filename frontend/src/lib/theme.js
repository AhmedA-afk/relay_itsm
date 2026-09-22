import { useCallback, useEffect, useState } from 'react'

const KEY = 'relay.theme'

/** auto follows the system; light and dark override it in both directions. */
export const MODES = ['auto', 'light', 'dark']

function read() {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'auto'
  } catch {
    return 'auto'
  }
}

/**
 * The appearance control.
 *
 * Apple's guidance is to follow the system rather than offer an app setting
 * (`dark-mode.md` › Best practices), so `auto` is the default and stays the
 * default until someone chooses otherwise. The explicit choices exist because
 * a browser is not a Mac: people run one dark app in a light desktop all the
 * time, and there is no system switch inside a tab.
 *
 * `auto` clears the attribute entirely, leaving prefers-color-scheme alone —
 * which is what the guarded selectors in styles.css expect. The resolved
 * appearance is also mirrored as a `.dark` class for shadcn's variants.
 */
export function useTheme() {
  const [mode, setMode] = useState(read)

  useEffect(() => {
    const root = document.documentElement
    if (mode === 'auto') delete root.dataset.theme
    else root.dataset.theme = mode
    try {
      if (mode === 'auto') localStorage.removeItem(KEY)
      else localStorage.setItem(KEY, mode)
    } catch { /* private mode: the choice lasts for this session only */ }
  }, [mode])

  // Keep the browser chrome in step while following the system.
  const resolved = useResolved(mode)

  // shadcn's dark: variants key off a class, not the media query, so the
  // resolved appearance — auto included — is mirrored onto <html>.
  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolved === 'dark')
  }, [resolved])

  return [mode, useCallback((m) => setMode(m), []), resolved]
}

function useResolved(mode) {
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false,
  )
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return undefined
    const on = (e) => setSystemDark(e.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return mode === 'auto' ? (systemDark ? 'dark' : 'light') : mode
}
