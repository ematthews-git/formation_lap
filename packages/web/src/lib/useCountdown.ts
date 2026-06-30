import { useEffect, useState } from 'react'

export interface Countdown {
  d: string
  h: string
  m: string
  s: string
  done: boolean
}

const PLACEHOLDER: Countdown = { d: '--', h: '--', m: '--', s: '--', done: false }

function compute(target: number): Countdown {
  const diff = target - Date.now()
  if (diff <= 0) return { d: '00', h: '00', m: '00', s: '00', done: true }
  const p = (n: number) => String(n).padStart(2, '0')
  return {
    d: p(Math.floor(diff / 86_400_000)),
    h: p(Math.floor((diff % 86_400_000) / 3_600_000)),
    m: p(Math.floor((diff % 3_600_000) / 60_000)),
    s: p(Math.floor((diff % 60_000) / 1000)),
    done: false,
  }
}

/**
 * Live countdown to `target` (a Date or ISO string), ticking once a second.
 * Ported from the mockup's component countdown logic.
 */
export function useCountdown(target: Date | string | undefined): Countdown {
  const [value, setValue] = useState<Countdown>(PLACEHOLDER)

  useEffect(() => {
    if (!target) {
      setValue(PLACEHOLDER)
      return
    }
    const ms = (target instanceof Date ? target : new Date(target)).getTime()
    if (Number.isNaN(ms)) {
      setValue(PLACEHOLDER)
      return
    }
    setValue(compute(ms))
    const timer = setInterval(() => setValue(compute(ms)), 1000)
    return () => clearInterval(timer)
  }, [target])

  return value
}
