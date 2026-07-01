/*
 * Map a list of finishing positions (1 = best) to a thin sparkline polyline,
 * ported from the mockup's `spark()` helper. The box is 84×26 with 2px padding;
 * position 1 sits at the top, position 14 at the bottom.
 */
const W = 84
const H = 26
const PAD = 2
const MAX_POS = 20 // bottom of the chart (positions worse than this are clamped)

export interface Point {
  x: number
  y: number
}

export interface Sparkline {
  points: string
  coords: Point[] // one per race finish, oldest → newest
  lastX: number
  lastY: number
}

export function buildSparkline(form: number[]): Sparkline {
  if (form.length === 0) return { points: '', coords: [], lastX: PAD, lastY: PAD }
  const pts = form.map((pos, i) => {
    const clamped = Math.min(Math.max(pos, 1), MAX_POS)
    const x = PAD + (W - PAD * 2) * (form.length > 1 ? i / (form.length - 1) : 0)
    const y = PAD + (H - PAD * 2) * ((clamped - 1) / (MAX_POS - 1))
    return { x: +x.toFixed(1), y: +y.toFixed(1) }
  })
  const last = pts[pts.length - 1]
  return {
    points: pts.map((p) => `${p.x},${p.y}`).join(' '),
    coords: pts,
    lastX: last.x,
    lastY: last.y,
  }
}
