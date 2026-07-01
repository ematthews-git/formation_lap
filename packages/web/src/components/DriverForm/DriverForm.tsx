import type { Driver, RaceResult, Standing } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState, ErrorState, LoadingState } from '../common/Status'
import { teamColorVar } from '../../lib/format'
import { Sparkline } from './Sparkline'
import styles from './DriverForm.module.css'

interface Props {
  drivers: Driver[] | undefined
  driversLoading: boolean
  driversError: boolean
  standings: Standing[] | undefined
  raceResults: RaceResult[] | undefined
}

interface Row {
  name: string
  team: string
  points: number | null
  last5: number[] // most-recent-last finishing positions
  lastFinish: number | null
}

/** driver_id → finishing positions across the season, oldest → newest. */
function formByDriver(results: RaceResult[] | undefined): Map<string, number[]> {
  const map = new Map<string, number[]>()
  if (!results) return map
  const byRound = [...results].sort((a, b) => a.round_number - b.round_number)
  for (const r of byRound) {
    const arr = map.get(r.driver_id) ?? []
    arr.push(r.position)
    map.set(r.driver_id, arr)
  }
  return map
}

/** WDC points by driver surname (standings.name is a full name). */
function pointsBySurname(standings: Standing[] | undefined): Map<string, number> {
  const map = new Map<string, number>()
  if (!standings) return map
  for (const s of standings.filter((x) => x.type === 'driver')) {
    const surname = s.name.toLowerCase().split(' ').slice(-1)[0]
    map.set(surname, s.points)
  }
  return map
}

function buildRows(
  drivers: Driver[],
  standings: Standing[] | undefined,
  results: RaceResult[] | undefined,
): Row[] {
  const points = pointsBySurname(standings)
  const form = formByDriver(results)

  const rows: Row[] = drivers.map((d) => {
    const surname = d.full_name.toLowerCase().split(' ').slice(-1)[0]
    const finishes = form.get(d.driver_id) ?? []
    return {
      name: d.full_name,
      team: d.team,
      points: points.get(surname) ?? null,
      last5: finishes.slice(-5),
      lastFinish: finishes.length ? finishes[finishes.length - 1] : null,
    }
  })

  // Order by championship points (drivers with points first, ties keep order).
  if (points.size > 0) {
    rows.sort((a, b) => (b.points ?? -1) - (a.points ?? -1))
  }
  return rows.slice(0, 10)
}

export function DriverForm({
  drivers,
  driversLoading,
  driversError,
  standings,
  raceResults,
}: Props) {
  const afterRound = standings?.find((s) => s.type === 'driver')?.after_round

  return (
    <Panel>
      <PanelHeader
        label="DRIVER_FORM"
        sub="TOP_10"
        meta={afterRound != null ? `CHAMPIONSHIP · AFTER R${afterRound}` : 'GRID'}
      />
      <div className={styles.headRow}>
        <span>#</span>
        <span>DRIVER</span>
        <span>TEAM</span>
        <span className={styles.center}>LAST 5</span>
        <span className={styles.right}>LAST</span>
        <span className={styles.right}>PTS</span>
      </div>

      {driversError ? (
        <ErrorState message="Could not load the driver grid" />
      ) : driversLoading && !drivers ? (
        <LoadingState label="LOADING GRID" />
      ) : drivers && drivers.length > 0 ? (
        buildRows(drivers, standings, raceResults).map((row, i) => (
          <div key={row.name} className={styles.row}>
            <span className={styles.accentBar} style={{ background: teamColorVar(row.team) }} />
            <span className={styles.pos}>{String(i + 1).padStart(2, '0')}</span>
            <span className={styles.name}>{row.name}</span>
            <span className={styles.team}>{row.team}</span>
            <span className={styles.center}>
              {row.last5.length > 0 ? (
                <Sparkline form={row.last5} color={teamColorVar(row.team)} />
              ) : (
                <span className={styles.placeholder}>—</span>
              )}
            </span>
            <span className={`${styles.right} ${styles.last}`}>
              {row.lastFinish != null ? `P${row.lastFinish}` : '—'}
            </span>
            <span className={styles.pts}>{row.points ?? '—'}</span>
          </div>
        ))
      ) : (
        <EmptyState label="NO DRIVERS" />
      )}
    </Panel>
  )
}
