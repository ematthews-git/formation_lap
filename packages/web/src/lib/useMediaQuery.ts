import { useEffect, useState } from 'react'

/**
 * Subscribe to a CSS media query and re-render when it flips. The initial value
 * is read synchronously so the first paint is already correct (this is a
 * client-only SPA — no SSR/hydration to worry about).
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches,
  )

  useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return matches
}
