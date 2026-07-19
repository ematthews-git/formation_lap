import { useEffect, useMemo, useState, type PointerEvent } from 'react'
import type { RaceTrace as ApiRaceTrace } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState, ErrorState, LoadingState } from '../common/Status'
import { prettifyCircuit, teamColorVar } from '../../lib/format'
import { useMediaQuery } from '../../lib/useMediaQuery'
import { useElementWidth } from '../../lib/useElementWidth'
import {
  buildAverageTrace,
  buildRaceTrace,
  formatLapTime,
  PACE_SMOOTH,
  raceFromApi,
  type DriverTrace,
  type RaceScope,
  type RaceTraceView,
  type TraceLine,
  type TrackStatus,
  type WeatherState,
} from '../../lib/raceTrace'
import styles from './RaceTrace.module.css'

/*
 * RACE_TRACE — lap-by-lap story of a race as a stack of lanes on one shared
 * lap axis: the pace pane (envelope bands with team-coloured lines inside, or
 * every classified driver individually), an excitement-index lane,
 * overtakes-per-lap bars, and the track-status + weather strips along the
 * x-axis. A selector switches between the races on record at this circuit and
 * a cross-race average view, where the strips become per-lap probability heat
 * maps. Data comes from /circuits/{id}/race-traces; every driver's team is the
 * one they raced for in that event, so lookbacks stay period-correct.
 */

const STATUS_CLASS: Record<TrackStatus, string> = {
  green: styles.stGreen,
  yellow: styles.stYellow,
  vsc: styles.stVsc,
  sc: styles.stSc,
  red: styles.stRed,
}

const STATUS_NAME: Record<TrackStatus, string> = {
  green: 'GREEN',
  yellow: 'YELLOW',
  vsc: 'VSC',
  sc: 'SAFETY CAR',
  red: 'RED FLAG',
}

/** Short in-strip tag for a wide status segment. */
const STATUS_TAG: Partial<Record<TrackStatus, string>> = {
  vsc: 'VSC',
  sc: 'SC',
  red: 'RED',
}

const WEATHER_CLASS: Record<Exclude<WeatherState, 'dry'>, string> = {
  damp: styles.wxDamp,
  wet: styles.wxWet,
}

/** Neutral shades for the average view's band mean lines. */
const toneColor = (tone: TraceLine['tone']): string =>
  tone === 'top' ? 'var(--text-num)' : 'var(--text-muted)'

const lineColor = (line: TraceLine): string =>
  line.team ? teamColorVar(line.team) : toneColor(line.tone)

interface Props {
  circuitId: string | undefined
  /** Most recent traces for the circuit, newest first (see useRaceTraces). */
  traces: ApiRaceTrace[] | undefined
  loading: boolean
  /** Query failure (network/5xx) — distinct from "no traces yet". */
  error?: boolean
}

export function RaceTrace({ circuitId, traces, loading, error }: Props) {
  const compact = useMediaQuery('(max-width: 750px)')
  const [wrapRef, width] = useElementWidth<HTMLDivElement>()
  // Selected race as an index into `races` (newest first) — indices stay unambiguous
  // even if a season ever contributes two races. 'avg' = the cross-race average.
  const [sel, setSel] = useState<number | 'avg'>(0)
  const [scope, setScope] = useState<RaceScope>('trios')
  const [hoverLap, setHoverLap] = useState<number | null>(null)

  const races = useMemo(() => (traces ?? []).map((t) => raceFromApi(t.trace)), [traces])
  const average = useMemo(() => buildAverageTrace(races), [races])

  // A new circuit gets a fresh selection (the old index would silently point at a
  // different year, or past the end of a shorter history).
  useEffect(() => {
    setSel(0)
    setHoverLap(null)
  }, [circuitId])

  const isAvg = sel === 'avg' && average != null
  const race = isAvg ? null : races[Math.min(sel === 'avg' ? 0 : sel, races.length - 1)]
  const view: RaceTraceView | null = isAvg
    ? { mode: 'average', average: average! }
    : race
      ? { mode: 'race', race, scope }
      : null

  const geom = useMemo(
    () => (view && width > 0 ? buildRaceTrace(view, width, compact) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [races, average, sel, scope, width, compact],
  )

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    if (!geom) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    if (x < geom.plot.x0 - 4 || x > geom.plot.x1 + 4) setHoverLap(null)
    else setHoverLap(geom.lapAt(x))
  }

  const label = isAvg ? average!.label : race?.label
  const crossBottom = geom
    ? geom.weather
      ? geom.weather.y + geom.weather.h
      : geom.status.y + geom.status.h
    : 0

  return (
    <Panel strong>
      <PanelHeader
        accent
        label="RACE_TRACE"
        sub={circuitId ? prettifyCircuit(circuitId).toUpperCase() : undefined}
        meta={label}
      />
      <div className={styles.body}>
        {loading ? (
          <LoadingState label="LOADING RACE TRACES" />
        ) : view ? (
          <>
            {/* view controls: race / average, and driver scope */}
            <div className={styles.controls}>
              <div className={styles.toggle}>
                {races.map((r, i) => (
                  <button
                    key={`${r.season}-${i}`}
                    type="button"
                    className={`${styles.btn} ${!isAvg && race === r ? styles.btnActive : ''}`}
                    onClick={() => setSel(i)}
                  >
                    {r.season}
                  </button>
                ))}
                {average && (
                  <button
                    type="button"
                    className={`${styles.btn} ${isAvg ? styles.btnActive : ''}`}
                    onClick={() => setSel('avg')}
                  >
                    AVG
                  </button>
                )}
              </div>
              <div className={styles.toggle}>
                <button
                  type="button"
                  className={`${styles.btn} ${scope === 'trios' || isAvg ? styles.btnActive : ''}`}
                  onClick={() => setScope('trios')}
                >
                  TOP/BOT 3
                </button>
                <button
                  type="button"
                  className={`${styles.btn} ${scope === 'all' && !isAvg ? styles.btnActive : ''}`}
                  onClick={() => setScope('all')}
                  disabled={isAvg}
                  title={isAvg ? 'Average trace is top/bottom-3 only' : undefined}
                >
                  ALL DRIVERS
                </button>
              </div>
            </div>

            <div ref={wrapRef} className={styles.chartWrap}>
              {geom && (
                <>
                  <svg
                    width={geom.width}
                    height={geom.height}
                    className={styles.svg}
                    role="img"
                    aria-label={`Race trace for ${label}: lap-by-lap pace, excitement index, overtakes per lap, and track status`}
                    onPointerMove={onMove}
                    onPointerDown={onMove}
                    onPointerLeave={() => setHoverLap(null)}
                  >
                    {/* SC/VSC/red columns tie the lanes together (race views) */}
                    {geom.neutralized.map((n, i) => (
                      <rect
                        key={`n${i}`}
                        x={n.x}
                        y={n.y0}
                        width={n.w}
                        height={n.y1 - n.y0}
                        className={styles.neutralShade}
                      />
                    ))}

                    {/* pace pane grid + ticks */}
                    {geom.pace.yTicks.map((t) => (
                      <g key={t.label}>
                        <line
                          x1={geom.plot.x0}
                          y1={t.y}
                          x2={geom.plot.x1}
                          y2={t.y}
                          className={styles.gridline}
                        />
                        <text x={geom.plot.x0 - 6} y={t.y + 2.5} className={styles.tickEnd}>
                          {t.label}
                        </text>
                      </g>
                    ))}
                    {geom.xTicks.map((t) => (
                      <line
                        key={`gx${t.x}`}
                        x1={t.x}
                        y1={geom.pace.box.y0}
                        x2={t.x}
                        y2={geom.pace.box.y1}
                        className={styles.gridlineFaint}
                      />
                    ))}
                    <text x={geom.plot.x0} y={geom.pace.box.y0 - 6} className={styles.laneLabel}>
                      RACE PACE · {PACE_SMOOTH > 1 ? `${PACE_SMOOTH}-LAP SMOOTH` : 'RAW'} · FASTER ▲
                      {isAvg && ` · MEAN OF ${average!.nRaces} RACES`}
                    </text>

                    {/* pace: envelopes first, lines inside, pit markers on top */}
                    {geom.pace.areas.map((a) => (
                      <path
                        key={a.tone}
                        d={a.d}
                        className={a.tone === 'top' ? styles.bandTop : styles.bandBottom}
                      />
                    ))}
                    {geom.pace.lines.map((line) => (
                      <g key={line.id}>
                        {line.segments.map((s, si) => (
                          <path
                            key={si}
                            d={s.d}
                            className={
                              s.interp
                                ? styles.lineInterp
                                : line.secondCar
                                  ? styles.lineSecond
                                  : styles.line
                            }
                            style={{ stroke: lineColor(line) }}
                          />
                        ))}
                        {line.pits.map((p, pi) => (
                          <circle
                            key={pi}
                            cx={p.x}
                            cy={p.y}
                            r={geom.pace.lines.length > 6 ? 2.4 : 2.8}
                            className={styles.pitDot}
                            style={{ fill: lineColor(line) }}
                          />
                        ))}
                        <text
                          x={line.endLabel.x}
                          y={line.endLabel.y + 3}
                          className={styles.endLabel}
                          style={{ fill: lineColor(line) }}
                        >
                          {line.endLabel.text}
                        </text>
                      </g>
                    ))}

                    {/* excitement lane */}
                    <text
                      x={geom.plot.x0}
                      y={geom.excitement.box.y0 - 6}
                      className={styles.laneLabel}
                    >
                      EXCITEMENT INDEX · 0–100{isAvg && ' · MEAN'}
                    </text>
                    <line
                      x1={geom.plot.x0}
                      y1={geom.excitement.box.y1}
                      x2={geom.plot.x1}
                      y2={geom.excitement.box.y1}
                      className={styles.laneBase}
                    />
                    <path d={geom.excitement.area} className={styles.exciteArea} />
                    <path d={geom.excitement.line} className={styles.exciteLine} />

                    {/* overtakes lane */}
                    <text
                      x={geom.plot.x0}
                      y={geom.overtakes.box.y0 - 6}
                      className={styles.laneLabel}
                    >
                      OVERTAKES / LAP{isAvg && ' · MEAN'}
                    </text>
                    <line
                      x1={geom.plot.x0}
                      y1={geom.overtakes.box.y1}
                      x2={geom.plot.x1}
                      y2={geom.overtakes.box.y1}
                      className={styles.laneBase}
                    />
                    {geom.overtakes.bars.map((b) => (
                      <rect
                        key={b.lap}
                        x={b.x}
                        y={b.y}
                        width={b.w}
                        height={b.h}
                        className={hoverLap === b.lap ? styles.barHot : styles.bar}
                      />
                    ))}
                    {/* selective label: the busiest lap only */}
                    {(() => {
                      const peak = geom.overtakes.bars.find(
                        (b) => b.count === geom.overtakes.max,
                      )
                      return peak ? (
                        <text x={peak.x + peak.w / 2} y={peak.y - 3} className={styles.barLabel}>
                          {Number.isInteger(peak.count) ? peak.count : peak.count.toFixed(1)}
                        </text>
                      ) : null
                    })()}

                    {/* status strip, then weather directly beneath it */}
                    {[geom.status, geom.weather].map(
                      (strip, si) =>
                        strip && (
                          <g key={si}>
                            <text
                              x={geom.plot.x0 - 6}
                              y={strip.y + strip.h / 2 + 2.5}
                              className={styles.stripSideLabel}
                            >
                              {strip.label}
                            </text>
                            {strip.segments?.map((s, i) => (
                              <g key={`sg${i}`}>
                                <rect
                                  x={s.x}
                                  y={strip.y}
                                  width={s.w}
                                  height={strip.h}
                                  className={
                                    si === 0
                                      ? STATUS_CLASS[s.kind as TrackStatus]
                                      : WEATHER_CLASS[s.kind as Exclude<WeatherState, 'dry'>]
                                  }
                                />
                                {s.labelled &&
                                  (si === 0 ? STATUS_TAG[s.kind as TrackStatus] : 'RAIN') && (
                                    <text
                                      x={s.x + s.w / 2}
                                      y={strip.y + strip.h - 2.5}
                                      className={styles.stripLabel}
                                    >
                                      {si === 0 ? STATUS_TAG[s.kind as TrackStatus] : 'RAIN'}
                                    </text>
                                  )}
                              </g>
                            ))}
                            {strip.heat?.map(
                              (c, i) =>
                                c.alpha > 0 && (
                                  <rect
                                    key={`h${i}`}
                                    x={c.x}
                                    y={strip.y}
                                    width={c.w}
                                    height={strip.h}
                                    fillOpacity={c.alpha}
                                    className={si === 0 ? styles.heatStatus : styles.heatRain}
                                  />
                                ),
                            )}
                          </g>
                        ),
                    )}

                    {/* x-axis lap ticks */}
                    {geom.xTicks.map((t) => (
                      <text key={t.label} x={t.x} y={geom.height - 5} className={styles.tickMid}>
                        {t.label}
                      </text>
                    ))}

                    {/* hover crosshair */}
                    {hoverLap != null && (
                      <line
                        x1={geom.lapX(hoverLap)}
                        y1={geom.pace.box.y0}
                        x2={geom.lapX(hoverLap)}
                        y2={crossBottom}
                        className={styles.crosshair}
                      />
                    )}
                  </svg>

                  {hoverLap != null && (
                    <Tooltip
                      view={view}
                      lap={hoverLap}
                      pos={{ x: geom.lapX(hoverLap), top: geom.pace.box.y0, width: geom.width }}
                    />
                  )}
                </>
              )}
            </div>

            <Legend view={view} />
            <div className={styles.footnote}>
              {isAvg
                ? `BANDS = TOP/BOTTOM-3 PACE ENVELOPE AVERAGED OVER ${average!.nRaces} RACES · STRIP OPACITY = PER-LAP PROBABILITY · HOVER FOR VALUES`
                : 'DASHED-DIM = PACE INTERPOLATED THROUGH PIT / NEUTRALISED LAPS · HOVER FOR RAW TIMES'}
            </div>
          </>
        ) : error ? (
          <ErrorState message="couldn't load race traces" />
        ) : (
          <EmptyState
            label="NO RACE TRACES"
            hint="available once the race-traces backfill has run for this circuit"
          />
        )}
      </div>
    </Panel>
  )
}

function Legend({ view }: { view: RaceTraceView }) {
  const isAvg = view.mode === 'average'
  const race = view.mode === 'race' ? view.race : null
  const seenStatus = race
    ? (['green', 'yellow', 'vsc', 'sc', 'red'] as TrackStatus[]).filter((s) =>
        race.trackStatus.includes(s),
      )
    : []
  const sawRain = race ? race.weather.some((w) => w !== 'dry') : false
  const teams = race ? [...new Set(race.drivers.map((d) => d.team))] : []

  return (
    <div className={styles.legend}>
      {race && view.mode === 'race' && view.scope === 'trios' && (
        <>
          <span className={styles.legendGroup}>TOP 3</span>
          {race.drivers.slice(0, 3).map((d) => (
            <DriverChip key={d.code} driver={d} />
          ))}
          <span className={styles.legendGroup}>BOTTOM 3</span>
          {race.drivers.slice(-3).map((d) => (
            <DriverChip key={d.code} driver={d} />
          ))}
        </>
      )}
      {race && view.mode === 'race' && view.scope === 'all' && (
        <>
          {teams.map((t) => (
            <span key={t} className={styles.legendItem}>
              <span className={styles.swatchDot} style={{ background: teamColorVar(t) }} />
              {t.toUpperCase()}
            </span>
          ))}
          <span className={styles.legendItem}>2ND CAR DASHED</span>
        </>
      )}
      {isAvg && (
        <>
          <span className={styles.legendItem}>
            <span className={`${styles.swatchStrip} ${styles.swatchBandTop}`} /> TOP 3 ENVELOPE
          </span>
          <span className={styles.legendItem}>
            <span className={`${styles.swatchStrip} ${styles.swatchBandBottom}`} /> BOTTOM 3
            ENVELOPE
          </span>
        </>
      )}
      <span className={styles.legendDivider} />
      <span className={styles.legendItem}>
        <span className={styles.swatchLine} /> EXCITEMENT
      </span>
      <span className={styles.legendItem}>
        <span className={styles.swatchBar} /> OVERTAKES
      </span>
      {!isAvg && (
        <span className={styles.legendItem}>
          <span className={styles.swatchPit} /> PIT STOP
        </span>
      )}
      <span className={styles.legendDivider} />
      {seenStatus.map((s) => (
        <span key={s} className={styles.legendItem}>
          <span className={`${styles.swatchStrip} ${STATUS_CLASS[s]}`} /> {STATUS_NAME[s]}
        </span>
      ))}
      {sawRain && (
        <span className={styles.legendItem}>
          <span className={`${styles.swatchStrip} ${styles.wxDamp}`} /> RAIN
        </span>
      )}
      {isAvg && (
        <>
          <span className={styles.legendItem}>
            <span className={`${styles.swatchStrip} ${styles.swatchHeatStatus}`} /> STATUS PROB
          </span>
          <span className={styles.legendItem}>
            <span className={`${styles.swatchStrip} ${styles.swatchHeatRain}`} /> RAIN PROB
          </span>
        </>
      )}
    </div>
  )
}

function DriverChip({ driver }: { driver: DriverTrace }) {
  return (
    <span className={styles.legendItem}>
      <span className={styles.swatchDot} style={{ background: teamColorVar(driver.team) }} />
      {driver.code}
    </span>
  )
}

const pctLabel = (p: number): string => `${Math.round(p * 100)}%`

function Tooltip({
  view,
  lap,
  pos,
}: {
  view: RaceTraceView
  lap: number
  pos: { x: number; top: number; width: number }
}) {
  const flipped = pos.x > pos.width * 0.62
  const style = {
    left: flipped ? pos.x - 12 : pos.x + 12,
    top: pos.top + 6,
    transform: flipped ? 'translateX(-100%)' : undefined,
  }

  if (view.mode === 'average') {
    const a = view.average
    const probs: [string, number][] = [
      ['SC', a.statusProb.sc[lap - 1]],
      ['VSC', a.statusProb.vsc[lap - 1]],
      ['YELLOW', a.statusProb.yellow[lap - 1]],
      ['RED', a.statusProb.red[lap - 1]],
      ['RAIN', a.rainProb[lap - 1]],
    ]
    return (
      <div className={styles.tooltip} style={style}>
        <div className={styles.tipHead}>
          LAP {lap}/{a.totalLaps} · {a.nRaces}-RACE AVG
        </div>
        <div className={styles.tipRow}>
          <span className={styles.tipCode}>TOP 3</span>
          <span className={styles.tipTime}>{formatLapTime(a.top3.mean[lap - 1])}</span>
        </div>
        <div className={styles.tipRow}>
          <span className={styles.tipCode}>BOT 3</span>
          <span className={styles.tipTime}>{formatLapTime(a.bottom3.mean[lap - 1])}</span>
        </div>
        <div className={styles.tipRule} />
        <div className={styles.tipMeta}>
          {probs
            .filter(([, p]) => p > 0)
            .map(([name, p]) => (
              <span key={name}>
                {name} {pctLabel(p)}
              </span>
            ))}
          <span>EXCITEMENT {Math.round(a.excitement[lap - 1])} AVG</span>
          <span>OVERTAKES {a.overtakes[lap - 1].toFixed(1)} AVG</span>
        </div>
      </div>
    )
  }

  const race = view.race
  const status = race.trackStatus[lap - 1]
  const weather = race.weather[lap - 1]
  const row = (d: DriverTrace) => {
    const t = d.lapTimes[lap - 1]
    return (
      <div key={d.code} className={styles.tipRow}>
        <span className={styles.swatchDot} style={{ background: teamColorVar(d.team) }} />
        <span className={styles.tipCode}>{d.code}</span>
        <span className={styles.tipTime}>{t != null ? formatLapTime(t) : '—'}</span>
        {d.pitLaps.includes(lap) && <span className={styles.tipPit}>PIT</span>}
      </div>
    )
  }
  return (
    <div className={styles.tooltip} style={style}>
      <div className={styles.tipHead}>
        LAP {lap}/{race.totalLaps} · {STATUS_NAME[status]}
        {weather !== 'dry' && ` · ${weather.toUpperCase()}`}
      </div>
      {view.scope === 'all' ? (
        <div className={styles.tipGridAll}>{race.drivers.map(row)}</div>
      ) : (
        <>
          {race.drivers.slice(0, 3).map(row)}
          <div className={styles.tipRule} />
          {race.drivers.slice(-3).map(row)}
        </>
      )}
      <div className={styles.tipRule} />
      <div className={styles.tipMeta}>
        <span>EXCITEMENT {race.excitement[lap - 1]}</span>
        <span>OVERTAKES {race.overtakes[lap - 1]}</span>
      </div>
    </div>
  )
}
