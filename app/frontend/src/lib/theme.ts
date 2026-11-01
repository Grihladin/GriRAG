// Light/dark mode: follows the system unless chosen; index.html applies it before React loads (no white flash).
type Theme = 'system' | 'light' | 'dark'

const systemDark = window.matchMedia('(prefers-color-scheme: dark)')

function getTheme(): Theme {
  const t = localStorage.getItem('theme')
  return t === 'light' || t === 'dark' ? t : 'system'
}

function apply() {
  const t = getTheme()
  document.documentElement.classList.toggle('dark', t === 'dark' || (t === 'system' && systemDark.matches))
}

// Flips light/dark; choosing what the system uses goes back to following it.
export function toggleTheme() {
  const dark = !document.documentElement.classList.contains('dark')
  if (dark === systemDark.matches) localStorage.removeItem('theme')
  else localStorage.setItem('theme', dark ? 'dark' : 'light')
  apply()
}

systemDark.addEventListener('change', apply)
