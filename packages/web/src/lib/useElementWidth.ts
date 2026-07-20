import { useCallback, useRef, useState } from 'react'

/**
 * Measure an element's content width via ResizeObserver so charts can render
 * at native pixel size (crisp 1px strokes, constant-size text) instead of
 * scaling a fixed viewBox. Returns 0 until the first measurement lands.
 *
 * Uses a callback ref (not useRef + useEffect) so the observer attaches the
 * moment the node mounts — the target may appear after the first render, e.g.
 * once a loading gate resolves, which an empty-deps effect would miss.
 */
export function useElementWidth<T extends HTMLElement>(): [(node: T | null) => void, number] {
  const [width, setWidth] = useState(0)
  const observerRef = useRef<ResizeObserver | null>(null)

  const ref = useCallback((node: T | null) => {
    observerRef.current?.disconnect()
    if (!node) return
    const measure = () => setWidth(Math.round(node.getBoundingClientRect().width))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(node)
    observerRef.current = ro
  }, [])

  return [ref, width]
}
