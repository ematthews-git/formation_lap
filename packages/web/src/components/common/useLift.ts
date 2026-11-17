import { useEffect, type RefObject } from 'react'
import styles from './Lift.module.css'

/** Class that gives a card its hover lift; pair with `useLift(ref)` for the tilt. */
export const liftClass = styles.lift

/** Strongest tilt, at the card's edge, in degrees. */
const MAX_TILT = 0.8

/**
 * Tilts the card a few degrees towards the pointer while it's over the card,
 * by writing --tilt-x / --tilt-y straight onto the element (no React renders
 * per mouse move). Skipped on touch devices and for reduced motion.
 */
export function useLift(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const canHover = window.matchMedia('(hover: hover) and (pointer: fine)')
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    let frame = 0

    const onMove = (e: PointerEvent) => {
      if (!canHover.matches || reduced.matches) return
      const r = el.getBoundingClientRect()
      // -0.5 … 0.5 across the card, 0 at its centre.
      const x = (e.clientX - r.left) / r.width - 0.5
      const y = (e.clientY - r.top) / r.height - 0.5
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        // The edge under the pointer dips away, like pressing on a floating pane.
        el.style.setProperty('--tilt-x', `${(-y * 2 * MAX_TILT).toFixed(2)}deg`)
        el.style.setProperty('--tilt-y', `${(x * 2 * MAX_TILT).toFixed(2)}deg`)
      })
    }
    const onLeave = () => {
      cancelAnimationFrame(frame)
      el.style.removeProperty('--tilt-x')
      el.style.removeProperty('--tilt-y')
    }

    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerleave', onLeave)
    return () => {
      cancelAnimationFrame(frame)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerleave', onLeave)
    }
  }, [ref])
}
