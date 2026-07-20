import { useEffect, useRef, useState } from 'react'

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2
}

const prefersReducedMotion = (): boolean =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * Eases a number toward `target` over `duration` ms whenever `target` changes,
 * resuming from wherever the previous animation left off so rapid toggles stay
 * smooth. Meant to drive per-frame layout tweens: feed the returned value into
 * a geometry calculation and the whole thing reflows continuously instead of
 * snapping. Honours prefers-reduced-motion by jumping straight to the target.
 */
export function useTween(target: number, duration = 280): number {
  const [value, setValue] = useState(target)
  const valueRef = useRef(target)
  const frame = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (valueRef.current === target || prefersReducedMotion()) {
      valueRef.current = target
      setValue(target)
      return
    }
    const from = valueRef.current
    const delta = target - from
    const start = performance.now()
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / duration)
      const v = from + delta * easeInOutCubic(p)
      valueRef.current = v
      setValue(v)
      if (p < 1) frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => {
      if (frame.current != null) cancelAnimationFrame(frame.current)
    }
  }, [target, duration])

  return value
}
