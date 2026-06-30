import type { Driver, Standing } from '../../api/types'
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
}

interface Row {
  name: string
  team: string
  points: number | null
  form: number[] | null
}

/** Combine the live driver grid with championship standings (when available). */
function buildRows(drivers: Driver[], standings: Standing[] | undefined): Row[] {
  const pointsByName = new Map<string, number>()
  if (standings) {
    for (const s of standings.filter((x) => x.type === 'driver')) {
      pointsByName.set(s.name.toLowerCase(), s.points)
    }
  }

  const rows: Row[] = drivers.map((d) => ({
    name: d.full_name,
    team: d.team,
    points: matchPoints(pointsByName, d.full_name),
    form: null, // results-derived; no endpoint yet
  }))

  // Order by championship points when we have them, else keep seed order.
  if (standings && standings.length > 0) {
    rows.sort((a, b) => (b.points ?? -1) - (a.points ?? -1))
  }
  return rows.slice(0, 10)
}

function matchPoints(map: Map<string, number>, fullName: string): number | null {
  const lower = fullName.toLowerCase()
  if (map.has(lower)) return map.get(lower)!
  const surname = lower.split(' ').slice(-1)[0]
  for (const [k, v] of map) if (k.includes(surname)) return v
  return null
}

export function DriverForm({ drivers, driversLoading, driversError, standings }: Props) {
  return (
    <Panel>
      <PanelHeader
        label="DRIVER_FORM"
        sub="TOP_10"
        meta={standings?.length ? 'CHAMPIONSHIP' : 'GRID'}
      />
      <div className={styles.headRow}>
        <span>#</span>
        <span>DRIVER</span>
        <span>TEAM</span>
        <span className={styles.center}>LAST 5</span>
        <span className={styles.center}>LAST</span>
        <span className={styles.right}>PTS</span>
      </div>

      {driversError ? (
        <ErrorState message="Could not load the driver grid" />
      ) : driversLoading && !drivers ? (
        <LoadingState label="LOADING GRID" />
      ) : drivers && drivers.length > 0 ? (
        buildRows(drivers, standings).map((row, i) => (
          <div key={row.name} className={styles.row}>
            <span className={styles.accentBar} style={{ background: teamColorVar(row.team) }} />
            <span className={styles.pos}>{String(i + 1).padStart(2, '0')}</span>
            <span className={styles.name}>{row.name}</span>
            <span className={styles.team}>{row.team}</span>
            <span className={styles.center}>
              {row.form ? (
                <Sparkline form={row.form} color={teamColorVar(row.team)} />
              ) : (
                <span className={styles.placeholder}>—</span>
              )}
            </span>
            <span className={`${styles.center} ${styles.last}`}>
              {row.form ? `P${row.form[row.form.length - 1]}` : '—'}
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
