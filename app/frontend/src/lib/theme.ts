// Light/dark mode: follows the system unless chosen; index.html applies it before React loads (no white flash).
export type Theme = 'system' | 'light' | 'dark'

const dark = window.matchMedia('(prefers-color-scheme: dark)')

export function getTheme(): Theme {
  const t = localStorage.getItem('theme')
  return t === 'light' || t === 'dark' ? t : 'system'
}

export function setTheme(t: Theme) {
  if (t === 'system') localStorage.removeItem('theme')
  else localStorage.setItem('theme', t)
  apply()
}

function apply() {
  const t = getTheme()
  document.documentElement.classList.toggle('dark', t === 'dark' || (t === 'system' && dark.matches))
}

dark.addEventListener('change', apply)
