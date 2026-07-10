/*
 * Geometry for the quali finish-vs-grid scatterplot. Mirrors the sparkline split:
 * pure maths here, thin SVG in QualiMetrics. x = grid position, y = mean classified
 * finish (y is inverted at render time so P1 sits at the top). Both axes share the
 * same 1..maxPos position scale.
 */
const W = 240
const H = 200
const PAD_L = 30 // room for the y ("FINISH") tick labels
const PAD_R = 12
const PAD_T = 12
const PAD_B = 26 // room for the x ("GRID") tick labels

export interface ScatterPoint {
  grid: number
  finish: number
  x: number
  y: number
}

export interface GridScatter {
  width: number
  height: number
  /** Inner plot rectangle (axis frame). */
  box: { x0: number; y0: number; x1: number; y1: number }
  maxPos: number
  /** This circuit's mean-finish-by-grid dots. */
  points: ScatterPoint[]
  /** Calendar-wide baseline dots (grey). */
  calendarPoints: ScatterPoint[]
  /** Identity reference (grid = finish) endpoints. */
  diagonal: { x1: number; y1: number; x2: number; y2: number }
}

/** Parse a `{ "1": meanFinish, ... }` map into numeric (grid, finish) pairs, grid-sorted. */
function toPairs(byGrid: Record<string, number> | undefined): [number, number][] {
  if (!byGrid) return []
  return Object.entries(byGrid)
    .map(([slot, finish]) => [Number(slot), finish] as [number, number])
    .filter(([g, f]) => Number.isFinite(g) && Number.isFinite(f))
    .sort((a, b) => a[0] - b[0])
}

function project(grid: number, finish: number, maxPos: number): { x: number; y: number } {
  const plotW = W - PAD_L - PAD_R
  const plotH = H - PAD_T - PAD_B
  const span = Math.max(1, maxPos - 1)
  const gx = Math.min(Math.max(grid, 1), maxPos)
  const fy = Math.min(Math.max(finish, 1), maxPos)
  return {
    x: +(PAD_L + plotW * ((gx - 1) / span)).toFixed(1),
    y: +(PAD_T + plotH * ((fy - 1) / span)).toFixed(1),
  }
}

export function buildGridScatter(
  byGrid: Record<string, number> | undefined,
  calendar: Record<string, number> | undefined,
): GridScatter {
  const circuitPairs = toPairs(byGrid)
  const calendarPairs = toPairs(calendar)

  // Axis top-end: the largest position seen in either series (grid slot or mean finish),
  // floored at 10 so a sparse track still reads as a full field, capped at 20.
  const seen = [
    ...circuitPairs.flat(),
    ...calendarPairs.flat(),
  ].filter((n) => Number.isFinite(n))
  const maxPos = seen.length
    ? Math.min(20, Math.max(10, Math.ceil(Math.max(...seen))))
    : 20

  const toPoint = ([grid, finish]: [number, number]): ScatterPoint => ({
    grid,
    finish,
    ...project(grid, finish, maxPos),
  })

  const a = project(1, 1, maxPos)
  const b = project(maxPos, maxPos, maxPos)

  return {
    width: W,
    height: H,
    box: { x0: PAD_L, y0: PAD_T, x1: W - PAD_R, y1: H - PAD_B },
    maxPos,
    points: circuitPairs.map(toPoint),
    calendarPoints: calendarPairs.map(toPoint),
    diagonal: { x1: a.x, y1: a.y, x2: b.x, y2: b.y },
  }
}
