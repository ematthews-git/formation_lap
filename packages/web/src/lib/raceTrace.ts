/*
 * Geometry for the race trace — pure maths here, thin SVG in RaceTrace.tsx
 * (mirrors the sparkline/gridScatter split). One shared lap x-scale feeds a
 * vertical stack of lanes: the main pace pane, an excitement-index lane, an
 * overtakes-per-lap lane, and the track-status + weather strips along the
 * x-axis.
 *
 * Three views share the geometry:
 *  - race/trios: top-3 and bottom-3 finishers as min–max envelope bands with
 *    team-coloured lines inside;
 *  - race/all: every classified driver as an individual line (no bands, the
 *    team's second car dashed);
 *  - average: the trio bands averaged across the seasons on record, with the
 *    status/weather strips switching from raw events to per-lap probability
 *    heat strips.
 *
 * Pace lanes plot lap time with faster at the top. Laps with no representative
 * pace (pit in/out laps, SC/VSC/red-flag running) are linearly interpolated so
 * the y-scale stays on green-flag racing pace — the interpolated stretches are
 * flagged so the component can render them dashed, and the status strip tells
 * the underlying story. A light 3-lap rolling mean smooths the display lines;
 * tooltips should surface the raw values.
 */

import type { RaceTraceBlob } from '../api/types'

export type TrackStatus = 'green' | 'yellow' | 'vsc' | 'sc' | 'red'
export type WeatherState = 'dry' | 'damp' | 'wet'

export interface DriverTrace {
  /** Three-letter driver code, e.g. "NOR". */
  code: string
  /** Team name — feeds teamColorVar for the line colour. */
  team: string
  /** The team's second entry — rendered dashed in the all-drivers view. */
  secondCar?: boolean
  finishPos: number
  /** Raw lap times in seconds, index 0 = lap 1; null = no time set. */
  lapTimes: (number | null)[]
  /** Laps (1-based) on which the driver pitted. */
  pitLaps: number[]
}

export interface RaceTraceData {
  season: number
  /** Display label for the race, e.g. "SAMPLE GP · 2025". */
  label: string
  totalLaps: number
  /** Per-lap arrays, index 0 = lap 1. */
  trackStatus: TrackStatus[]
  weather: WeatherState[]
  /** Raw excitement index 0–100 per lap (smoothed at render). */
  excitement: number[]
  overtakes: number[]
  /** All classified drivers, sorted by finishing position. */
  drivers: DriverTrace[]
}

/** Per-lap min/mean/max of a trio's pace, averaged across the races on record. */
export interface BandAverageSeries {
  upper: number[]
  mean: number[]
  lower: number[]
}

export interface RaceTraceAverage {
  label: string
  totalLaps: number
  nRaces: number
  /** Per-lap probability (0–1) that a race here runs each non-green status. */
  statusProb: { yellow: number[]; vsc: number[]; sc: number[]; red: number[] }
  /** Per-lap probability of rain-affected running. */
  rainProb: number[]
  /** Cross-race means. */
  excitement: number[]
  overtakes: number[]
  top3: BandAverageSeries
  bottom3: BandAverageSeries
}

const STATUS_TOKENS = new Set<TrackStatus>(['green', 'yellow', 'vsc', 'sc', 'red'])
const WEATHER_TOKENS = new Set<WeatherState>(['dry', 'damp', 'wet'])

// Display smoothing windows (laps). 1 = raw per-lap, no smoothing; 3 = 3-lap
// rolling mean. Exported so the pace lane label can reflect the current setting.
export const PACE_SMOOTH = 3
export const EXCITE_SMOOTH = 1

/** Map one API trace blob onto the render shape.

 * Teams come straight from the blob — the backend snapshots each driver's team from
 * that race's own session, so lookbacks show period-correct lineups. Only classified
 * finishers are kept: a DNF's null-padded tail would otherwise be interpolated into a
 * misleading flatline (the blob retains DNFs for a future retirement-marker treatment).
 */
export function raceFromApi(blob: RaceTraceBlob): RaceTraceData {
  const drivers = blob.drivers
    .filter((d) => d.classified)
    .sort((a, b) => a.finish_pos - b.finish_pos)
    .map((d) => ({
      code: d.code,
      team: d.team,
      secondCar: d.second_car,
      finishPos: d.finish_pos,
      lapTimes: d.lap_times,
      pitLaps: d.pit_laps,
    }))
  return {
    season: blob.season,
    label: `${blob.event_name.toUpperCase()} · ${blob.season}`,
    totalLaps: blob.total_laps,
    trackStatus: blob.track_status.map((s) =>
      STATUS_TOKENS.has(s as TrackStatus) ? (s as TrackStatus) : 'green',
    ),
    weather: blob.weather.map((w) =>
      WEATHER_TOKENS.has(w as WeatherState) ? (w as WeatherState) : 'dry',
    ),
    excitement: blob.excitement,
    overtakes: blob.overtakes,
    drivers,
  }
}

/**
 * Cross-race average of the traces on record — the "AVG" view. Per-lap probabilities
 * and means are taken over the races that reached that lap (race lengths vary with
 * red flags / layout tweaks), and the trio pace bands average *cleaned* series so one
 * year's safety car doesn't pollute laps other years raced. Null with fewer than two
 * races — an average of one race is just that race.
 */
export function buildAverageTrace(races: RaceTraceData[]): RaceTraceAverage | null {
  if (races.length < 2) return null
  const maxLaps = Math.max(...races.map((r) => r.totalLaps))

  const prob = (test: (r: RaceTraceData, lapIdx: number) => boolean): number[] =>
    Array.from({ length: maxLaps }, (_, i) => {
      const covering = races.filter((r) => r.totalLaps > i)
      return covering.length
        ? covering.filter((r) => test(r, i)).length / covering.length
        : 0
    })

  const mean = (pick: (r: RaceTraceData) => number[]): number[] =>
    Array.from({ length: maxLaps }, (_, i) => {
      const vals = races
        .filter((r) => r.totalLaps > i)
        .map((r) => pick(r)[i])
        .filter((v) => v != null && Number.isFinite(v))
      return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0
    })

  const band = (pick: (r: RaceTraceData) => DriverTrace[]): BandAverageSeries => {
    const upper = new Array<number>(maxLaps).fill(0)
    const meanArr = new Array<number>(maxLaps).fill(0)
    const lower = new Array<number>(maxLaps).fill(0)
    const counts = new Array<number>(maxLaps).fill(0)
    for (const race of races) {
      const trio = pick(race)
      if (!trio.length) continue
      const series = trio.map((d) => cleanedPaceSeries(d, race.trackStatus, race.totalLaps))
      for (let l = 0; l < race.totalLaps; l++) {
        const ts = series.map((s) => s[l])
        upper[l] += Math.min(...ts)
        meanArr[l] += ts.reduce((a, b) => a + b, 0) / ts.length
        lower[l] += Math.max(...ts)
        counts[l]++
      }
    }
    const div = (arr: number[]) => arr.map((v, i) => (counts[i] ? v / counts[i] : 0))
    return { upper: div(upper), mean: div(meanArr), lower: div(lower) }
  }

  return {
    label: `${races.length}-RACE AVG`,
    totalLaps: maxLaps,
    nRaces: races.length,
    statusProb: {
      yellow: prob((r, i) => r.trackStatus[i] === 'yellow'),
      vsc: prob((r, i) => r.trackStatus[i] === 'vsc'),
      sc: prob((r, i) => r.trackStatus[i] === 'sc'),
      red: prob((r, i) => r.trackStatus[i] === 'red'),
    },
    rainProb: prob((r, i) => r.weather[i] !== 'dry'),
    excitement: mean((r) => r.excitement),
    overtakes: mean((r) => r.overtakes),
    top3: band((r) => r.drivers.slice(0, 3)),
    bottom3: band((r) => r.drivers.slice(-3)),
  }
}

export type RaceScope = 'trios' | 'all'

export type RaceTraceView =
  | { mode: 'race'; race: RaceTraceData; scope: RaceScope }
  | { mode: 'average'; average: RaceTraceAverage }

/* ---- layout constants ---- */
const PAD_L = 48 // room for the pace tick labels
const PAD_R = 40 // room for the line-end labels
const PAD_T = 8
const LANE_GAP = 18 // gap between lanes — fits the small lane label
const EXCITE_H = 46
const OVERTAKE_H = 42
const STATUS_GAP = 8
const STATUS_H = 10
const WEATHER_H = 9
const WEATHER_GAP = 3
const AXIS_H = 18

export interface Box {
  x0: number
  y0: number
  x1: number
  y1: number
}

export interface StripSegment {
  x: number
  w: number
  kind: TrackStatus | WeatherState
  /** Wide enough to carry an in-segment text label. */
  labelled: boolean
}

/** One lap-cell of a probability heat strip. */
export interface HeatCell {
  x: number
  w: number
  /** Probability 0–1 at this lap. */
  p: number
  /** Display opacity, scaled to the strip's peak. */
  alpha: number
}

export interface StripGeom {
  y: number
  h: number
  /** Small side label left of the strip, e.g. "STATUS" / "RAIN %". */
  label: string
  /** Raw events (race views)... */
  segments?: StripSegment[]
  /** ...or per-lap probabilities (average view). */
  heat?: HeatCell[]
}

export interface PathSegment {
  d: string
  /** Interpolated (non-representative) stretch — rendered dashed/dim. */
  interp: boolean
}

export interface TraceLine {
  /** Driver code, or "TOP 3" / "BOT 3" for the average view's mean lines. */
  id: string
  /** Team for the line colour; null = neutral (average view). */
  team: string | null
  /** Which band a neutral line belongs to — picks the neutral shade. */
  tone: 'top' | 'bottom' | null
  secondCar: boolean
  segments: PathSegment[]
  pits: { x: number; y: number }[]
  endLabel: { x: number; y: number; text: string }
}

export interface RaceTraceGeom {
  width: number
  height: number
  plot: { x0: number; x1: number }
  pace: {
    box: Box
    yTicks: { y: number; label: string }[]
    /** Min–max envelopes (empty in the all-drivers view). */
    areas: { d: string; tone: 'top' | 'bottom' }[]
    lines: TraceLine[]
  }
  /** SC/VSC/red columns shaded across the whole lane stack (race views only). */
  neutralized: { x: number; w: number; y0: number; y1: number }[]
  excitement: { box: Box; line: string; area: string }
  overtakes: {
    box: Box
    bars: { x: number; y: number; w: number; h: number; count: number; lap: number }[]
    max: number
  }
  status: StripGeom
  weather: StripGeom | null
  xTicks: { x: number; label: string }[]
  /** Map a lap (1-based) to its centre x, and a pointer x back to a lap. */
  lapX: (lap: number) => number
  lapAt: (x: number) => number
}

/** Centred rolling mean; window shrinks at the edges. */
function rollingMean(v: number[], w: number): number[] {
  const half = Math.floor(w / 2)
  return v.map((_, i) => {
    const lo = Math.max(0, i - half)
    const hi = Math.min(v.length - 1, i + half)
    let sum = 0
    for (let j = lo; j <= hi; j++) sum += v[j]
    return sum / (hi - lo + 1)
  })
}

/**
 * Replace non-representative laps (pit in/out, SC/VSC/red, missing times) with
 * a linear interpolation between the surrounding representative laps, so the
 * display line and the y-domain stay on racing pace. Returns the cleaned
 * series plus a per-lap flag marking the interpolated stretches.
 */
function cleanPace(
  driver: DriverTrace,
  status: TrackStatus[],
  laps: number,
): { series: number[]; interp: boolean[] } {
  const pitSet = new Set(driver.pitLaps)
  const interp: boolean[] = []
  const raw: (number | null)[] = []
  for (let l = 1; l <= laps; l++) {
    const t = driver.lapTimes[l - 1] ?? null
    const s = status[l - 1] ?? 'green'
    const flagged =
      t == null || s === 'sc' || s === 'vsc' || s === 'red' || pitSet.has(l) || pitSet.has(l - 1)
    interp.push(flagged)
    raw.push(t)
  }
  const series = new Array<number>(laps)
  let i = 0
  while (i < laps) {
    if (!interp[i] && raw[i] != null) {
      series[i] = raw[i] as number
      i++
      continue
    }
    // A flagged run [i..j]: bridge from the last good lap to the next one.
    let j = i
    while (j < laps - 1 && (interp[j + 1] || raw[j + 1] == null)) j++
    const a = i > 0 ? series[i - 1] : null
    const b = j < laps - 1 && raw[j + 1] != null && !interp[j + 1] ? (raw[j + 1] as number) : null
    for (let k = i; k <= j; k++) {
      if (a != null && b != null) series[k] = a + ((b - a) * (k - i + 1)) / (j - i + 2)
      else series[k] = a ?? b ?? 0
      interp[k] = true
    }
    i = j + 1
  }
  return { series, interp }
}

/** Cleaned (interpolated, unsmoothed) pace series — used by cross-race averaging
 * so one season's SC laps don't pollute the mean. */
export function cleanedPaceSeries(
  driver: DriverTrace,
  status: TrackStatus[],
  laps: number,
): number[] {
  return cleanPace(driver, status, laps).series
}

/** Break a point series into maximal solid/interp path segments. Interp
 * segments are extended one point each side so they visually connect. */
function toSegments(pts: { x: number; y: number }[], interp: boolean[]): PathSegment[] {
  const segs: PathSegment[] = []
  let start = 0
  for (let i = 1; i <= pts.length; i++) {
    if (i === pts.length || interp[i] !== interp[start]) {
      const isInterp = interp[start]
      const lo = isInterp ? Math.max(0, start - 1) : start
      const hi = isInterp ? Math.min(pts.length - 1, i) : i - 1
      if (hi > lo) {
        const d = pts
          .slice(lo, hi + 1)
          .map((p, k) => `${k === 0 ? 'M' : 'L'}${p.x},${p.y}`)
          .join(' ')
        segs.push({ d, interp: isInterp })
      }
      start = i
    }
  }
  return segs
}

/** Run-length encode a per-lap kind array into pixel strip segments. */
function toStrip<K extends TrackStatus | WeatherState>(
  kinds: K[],
  laps: number,
  edge: (lap: number) => number,
  skip?: K,
): StripSegment[] {
  const segs: StripSegment[] = []
  let start = 1
  for (let l = 2; l <= laps + 1; l++) {
    if (l > laps || kinds[l - 1] !== kinds[start - 1]) {
      const kind = kinds[start - 1]
      if (kind !== skip) {
        const x = edge(start - 1)
        const w = edge(l - 1) - x
        segs.push({ x: +x.toFixed(1), w: +w.toFixed(1), kind, labelled: w >= 26 })
      }
      start = l
    }
  }
  return segs
}

/** Per-lap probabilities → heat cells with opacity scaled to the strip's peak. */
function toHeat(probs: number[], laps: number, edge: (lap: number) => number): HeatCell[] {
  const peak = Math.max(...probs.slice(0, laps), 0)
  if (peak <= 0) return []
  return probs.slice(0, laps).map((p, i) => {
    const x = edge(i)
    return {
      x: +x.toFixed(1),
      w: +(edge(i + 1) - x).toFixed(1),
      p,
      alpha: p > 0 ? +(0.12 + 0.88 * (p / peak)).toFixed(2) : 0,
    }
  })
}

const formatLapTime = (t: number): string => {
  const m = Math.floor(t / 60)
  const s = t - m * 60
  return `${m}:${s.toFixed(1).padStart(4, '0')}`
}

/** Push overlapping line-end labels apart (min separation), clamped to the pane. */
function decollide(ys: number[], minGap: number, y0: number, y1: number): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y)
  for (let k = 1; k < order.length; k++) {
    if (order[k].y - order[k - 1].y < minGap) order[k].y = order[k - 1].y + minGap
  }
  // If the pass pushed labels past the bottom, walk them back up.
  const over = order.length ? order[order.length - 1].y - y1 : 0
  if (over > 0) {
    order[order.length - 1].y = y1
    for (let k = order.length - 2; k >= 0; k--) {
      if (order[k + 1].y - order[k].y < minGap) order[k].y = order[k + 1].y - minGap
    }
  }
  const out = new Array<number>(ys.length)
  for (const o of order) out[o.i] = Math.max(y0, o.y)
  return out
}

export function buildRaceTrace(
  view: RaceTraceView,
  width: number,
  compact: boolean,
  /** 0 = full stack; 1 = pace pane expanded, excitement/overtakes collapsed. */
  expand = 0,
): RaceTraceGeom {
  const laps = view.mode === 'race' ? view.race.totalLaps : view.average.totalLaps
  const plotW = Math.max(1, width - PAD_L - PAD_R)
  const edge = (lap: number) => PAD_L + (lap / laps) * plotW
  const lapX = (lap: number) => +(PAD_L + ((lap - 0.5) / laps) * plotW).toFixed(1)
  const lapAt = (x: number) =>
    Math.min(laps, Math.max(1, Math.ceil(((x - PAD_L) / plotW) * laps)))

  const allDrivers = view.mode === 'race' && view.scope === 'all'

  /* ---- vertical stack ----
   * `expand` (0..1) grows the pace pane while the excitement and overtakes
   * lanes concertina shut into it. The freed vertical space is exactly what the
   * pace pane absorbs, so the status/weather strips and the overall height stay
   * fixed — nothing below the chart reflows mid-animation. `f` is clamped just
   * above zero so the collapsing lanes never divide by a zero height. */
  const f = Math.max(0.001, 1 - expand)
  let y = PAD_T
  y += 10 // lane-label line above the pace pane
  const paceBase = (compact ? 150 : 200) + (allDrivers ? 56 : 0)
  const freed = LANE_GAP + EXCITE_H + LANE_GAP + OVERTAKE_H
  const paceH = paceBase + (1 - f) * freed
  const paceBox: Box = { x0: PAD_L, y0: y, x1: PAD_L + plotW, y1: y + paceH }
  y = paceBox.y1 + LANE_GAP * f
  const exciteBox: Box = { x0: PAD_L, y0: y, x1: PAD_L + plotW, y1: y + EXCITE_H * f }
  y = exciteBox.y1 + LANE_GAP * f
  const overtakeBox: Box = { x0: PAD_L, y0: y, x1: PAD_L + plotW, y1: y + OVERTAKE_H * f }
  y = overtakeBox.y1 + STATUS_GAP
  const statusY = y
  y += STATUS_H

  // Weather sits directly under the status strip; drop it when there is
  // nothing to show (all-dry race / zero rain probability).
  const hasWeather =
    view.mode === 'race'
      ? view.race.weather.some((w) => w !== 'dry')
      : view.average.rainProb.some((p) => p > 0)
  let weatherY = 0
  if (hasWeather) {
    weatherY = y + WEATHER_GAP
    y = weatherY + WEATHER_H
  }
  const height = y + AXIS_H

  /* ---- pace series to draw ---- */
  interface Row {
    id: string
    team: string | null
    tone: 'top' | 'bottom' | null
    secondCar: boolean
    series: number[]
    interp: boolean[]
    pitLaps: number[]
  }
  let rows: Row[]
  let trios: { tone: 'top' | 'bottom'; members: Row[] }[] = []

  if (view.mode === 'race') {
    const toRow = (d: DriverTrace): Row => {
      const c = cleanPace(d, view.race.trackStatus, laps)
      return {
        id: d.code,
        team: d.team,
        tone: null,
        secondCar: d.secondCar ?? false,
        series: rollingMean(c.series, PACE_SMOOTH),
        interp: c.interp,
        pitLaps: d.pitLaps,
      }
    }
    if (allDrivers) {
      rows = view.race.drivers.map(toRow)
    } else {
      const top = view.race.drivers.slice(0, 3).map(toRow)
      const bottom = view.race.drivers.slice(-3).map(toRow)
      rows = [...top, ...bottom]
      trios = [
        { tone: 'top', members: top },
        { tone: 'bottom', members: bottom },
      ]
    }
  } else {
    const noInterp = new Array(laps).fill(false)
    const bandRows = (tone: 'top' | 'bottom', id: string, b: BandAverageSeries): Row[] => [
      // Only the mean is drawn as a line; upper/lower feed the envelope and
      // the y-domain.
      { id, team: null, tone, secondCar: false, series: rollingMean(b.mean, PACE_SMOOTH), interp: noInterp, pitLaps: [] },
      { id: `${id}·hi`, team: null, tone, secondCar: false, series: rollingMean(b.upper, PACE_SMOOTH), interp: noInterp, pitLaps: [] },
      { id: `${id}·lo`, team: null, tone, secondCar: false, series: rollingMean(b.lower, PACE_SMOOTH), interp: noInterp, pitLaps: [] },
    ]
    const top = bandRows('top', 'TOP 3', view.average.top3)
    const bottom = bandRows('bottom', 'BOT 3', view.average.bottom3)
    rows = [top[0], bottom[0]]
    trios = [
      { tone: 'top', members: top },
      { tone: 'bottom', members: bottom },
    ]
  }

  const domainRows = trios.length ? trios.flatMap((t) => t.members) : rows
  const values = domainRows.flatMap((r) => r.series)
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const pad = Math.max(0.4, (hi - lo) * 0.07)
  const tMin = lo - pad
  const tMax = hi + pad
  const paceY = (t: number) =>
    +(paceBox.y0 + ((t - tMin) / (tMax - tMin)) * (paceBox.y1 - paceBox.y0)).toFixed(1)

  // Three ticks on half-second boundaries across the domain.
  const tickLo = Math.ceil(tMin * 2) / 2
  const tickHi = Math.floor(tMax * 2) / 2
  const tickMid = Math.round(tickLo + tickHi) / 2
  const yTicks = [...new Set([tickLo, tickMid, tickHi])].map((t) => ({
    y: paceY(t),
    label: formatLapTime(t),
  }))

  /* ---- envelope areas ---- */
  const areas = trios.map(({ tone, members }) => {
    const upper: string[] = []
    const lower: string[] = []
    for (let l = 1; l <= laps; l++) {
      const ts = members.map((m) => m.series[l - 1])
      const x = lapX(l)
      // Faster (smaller time) sits higher, so min-time is the band's top edge;
      // ±2.5px keeps the envelope reading as one thick line when the trio is close.
      upper.push(`${x},${+(paceY(Math.min(...ts)) - 2.5).toFixed(1)}`)
      lower.push(`${x},${+(paceY(Math.max(...ts)) + 2.5).toFixed(1)}`)
    }
    const d =
      upper.map((p, i) => `${i === 0 ? 'M' : 'L'}${p}`).join(' ') +
      ' ' +
      lower.reverse().map((p) => `L${p}`).join(' ') +
      ' Z'
    return { d, tone }
  })

  /* ---- lines ---- */
  const endYs = decollide(
    rows.map((r) => paceY(r.series[laps - 1])),
    allDrivers ? (compact ? 10 : 11) : 11,
    paceBox.y0 + 4,
    paceBox.y1 - 2,
  )
  const lines: TraceLine[] = rows.map((r, i) => {
    const pts = r.series.map((t, k) => ({ x: lapX(k + 1), y: paceY(t) }))
    return {
      id: r.id,
      team: r.team,
      tone: r.tone,
      secondCar: r.secondCar,
      segments: toSegments(pts, r.interp),
      pits: r.pitLaps
        .filter((l) => l >= 1 && l <= laps)
        .map((l) => ({ x: lapX(l), y: paceY(r.series[l - 1]) })),
      endLabel: { x: +(PAD_L + plotW + 6).toFixed(1), y: endYs[i], text: r.id },
    }
  })
  // Slowest first so the front-runners draw on top in the all-drivers view.
  if (allDrivers) lines.reverse()

  /* ---- neutralized (SC/VSC/red) columns, shaded across the whole stack ---- */
  const stackBottom = hasWeather ? weatherY + WEATHER_H : statusY + STATUS_H
  const neutralized =
    view.mode === 'race'
      ? toStrip(view.race.trackStatus, laps, edge)
          .filter((s) => s.kind === 'sc' || s.kind === 'vsc' || s.kind === 'red')
          .map((s) => ({ x: s.x, w: s.w, y0: paceBox.y0, y1: stackBottom }))
      : []

  /* ---- excitement ---- */
  const exciteSrc = view.mode === 'race' ? view.race.excitement : view.average.excitement
  const excite = rollingMean(exciteSrc.slice(0, laps), EXCITE_SMOOTH)
  const exciteY = (v: number) =>
    +(exciteBox.y1 - (Math.max(0, Math.min(100, v)) / 100) * (exciteBox.y1 - exciteBox.y0)).toFixed(1)
  const excitePts = excite.map((v, i) => `${lapX(i + 1)},${exciteY(v)}`)
  const exciteLine = excitePts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p}`).join(' ')
  const exciteArea = `${exciteLine} L${lapX(laps)},${exciteBox.y1} L${lapX(1)},${exciteBox.y1} Z`

  /* ---- overtakes ---- */
  const counts = (view.mode === 'race' ? view.race.overtakes : view.average.overtakes).slice(0, laps)
  const maxCount = Math.max(0.001, ...counts)
  const slotW = plotW / laps
  const barW = Math.max(1.5, +(slotW * 0.62).toFixed(1))
  // Bar heights track the (collapsing) lane box, leaving 12px headroom at f=1
  // for the peak-lap label; the headroom scales away with the lane.
  const barSpan = Math.max(0, overtakeBox.y1 - overtakeBox.y0 - 12 * f)
  const bars = counts
    .map((count, i) => {
      const h = +((count / maxCount) * barSpan).toFixed(1)
      return {
        lap: i + 1,
        count,
        x: +(lapX(i + 1) - barW / 2).toFixed(1),
        y: +(overtakeBox.y1 - h).toFixed(1),
        w: barW,
        h,
      }
    })
    .filter((b) => b.count > 0)

  /* ---- status & weather strips ---- */
  let status: StripGeom
  let weather: StripGeom | null = null
  if (view.mode === 'race') {
    status = {
      y: statusY,
      h: STATUS_H,
      label: 'STATUS',
      segments: toStrip(view.race.trackStatus, laps, edge),
    }
    if (hasWeather) {
      weather = {
        y: weatherY,
        h: WEATHER_H,
        label: 'RAIN',
        segments: toStrip(view.race.weather, laps, edge, 'dry'),
      }
    }
  } else {
    // Any non-green status at a lap is mutually exclusive within one race, so
    // the per-kind probabilities sum to P(not green).
    const p = view.average.statusProb
    const combined = p.yellow.map((_, i) => p.yellow[i] + p.vsc[i] + p.sc[i] + p.red[i])
    status = {
      y: statusY,
      h: STATUS_H,
      label: 'STATUS %',
      heat: toHeat(combined, laps, edge),
    }
    if (hasWeather) {
      weather = {
        y: weatherY,
        h: WEATHER_H,
        label: 'RAIN %',
        heat: toHeat(view.average.rainProb, laps, edge),
      }
    }
  }

  const xTicks: { x: number; label: string }[] = []
  for (let l = 10; l <= laps - 4; l += 10) xTicks.push({ x: lapX(l), label: `L${l}` })
  xTicks.unshift({ x: lapX(1), label: 'L1' })
  xTicks.push({ x: lapX(laps), label: `L${laps}` })

  return {
    width,
    height,
    plot: { x0: PAD_L, x1: PAD_L + plotW },
    pace: { box: paceBox, yTicks, areas, lines },
    neutralized,
    excitement: { box: exciteBox, line: exciteLine, area: exciteArea },
    overtakes: { box: overtakeBox, bars, max: maxCount },
    status,
    weather,
    xTicks,
    lapX,
    lapAt,
  }
}

export { formatLapTime }
