import { useEffect, useRef, useState } from 'react'

const DURATION_MS = 700

function easeOutCubic(t: number): number {
  return 1 - (1 - t) ** 3
}

/**
 * Animates from 0 up to `target` over ~0.7s whenever `target` changes — gives
 * freshly-loaded numeric tiles a count-up reveal instead of popping straight
 * in. Returns null while `target` itself is null/undefined so callers can
 * still render an empty-state dash.
 */
export function useCountUp(target: number | null | undefined): number | null {
  const [value, setValue] = useState<number | null>(() => (target != null ? 0 : null))
  const frame = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (target == null) {
      setValue(null)
      return
    }
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / DURATION_MS)
      setValue(target * easeOutCubic(t))
      if (t < 1) frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => {
      if (frame.current != null) cancelAnimationFrame(frame.current)
    }
  }, [target])

  return value
}
