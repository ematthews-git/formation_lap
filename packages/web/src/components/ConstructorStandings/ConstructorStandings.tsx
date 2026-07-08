import type { Standing } from '../../api/types'
import { CollapsiblePanel } from '../common/CollapsiblePanel'
import { EmptyState, ErrorState, LoadingState } from '../common/Status'
import { constructorKey, teamColorVar } from '../../lib/format'
import styles from './ConstructorStandings.module.css'

interface Props {
  standings: Standing[] | undefined
  /** Previous season's final standings — the "LAST" column. */
  lastSeason: Standing[] | undefined
  loading: boolean
  error: boolean
}

/** Trim the verbose entrant suffix ("Alpine F1 Team" → "Alpine") to fit the column. */
function shortTeam(name: string): string {
  return name.replace(/\s+F1\s+Team$/i, '').replace(/\s+Team$/i, '')
}

export function ConstructorStandings({
  standings,
  lastSeason,
  loading,
  error,
}: Props) {
  const rows = (standings ?? [])
    .filter((s) => s.type === 'constructor')
    .sort((a, b) => a.position - b.position)
  const afterRound = rows[0]?.after_round

  // Last season's finishing position, keyed by team lineage so a rebranded team
  // (e.g. Sauber → Audi) still lines up; a new entrant has no prior finish.
  const lastFinishByKey = new Map<string, number>()
  for (const s of lastSeason ?? []) {
    if (s.type === 'constructor') {
      lastFinishByKey.set(constructorKey(s.name), s.position)
    }
  }

  return (
    <CollapsiblePanel
      label="CONSTRUCTORS"
      meta={afterRound != null ? `CHAMPIONSHIP · AFTER R${afterRound}` : 'GRID'}
    >
      <div className={styles.headRow}>
        <span>#</span>
        <span>TEAM</span>
        <span className={styles.right}>LAST</span>
        <span className={styles.right}>PTS</span>
      </div>

      {error ? (
        <ErrorState message="Could not load constructor standings" />
      ) : loading && !standings ? (
        <LoadingState label="LOADING STANDINGS" />
      ) : rows.length > 0 ? (
        rows.map((s) => {
          const lastYr = lastFinishByKey.get(constructorKey(s.name)) ?? null
          return (
            <div key={s.name} className={styles.row}>
              <span
                className={styles.accentBar}
                style={{ background: teamColorVar(s.name) }}
              />
              <span className={styles.pos}>
                {String(s.position).padStart(2, '0')}
              </span>
              <span className={styles.team}>{shortTeam(s.name)}</span>
              <span className={`${styles.right} ${styles.lastYr}`}>
                {lastYr != null ? `P${lastYr}` : '—'}
              </span>
              <span className={styles.pts}>{s.points}</span>
            </div>
          )
        })
      ) : (
        <EmptyState label="NO STANDINGS" />
      )}
    </CollapsiblePanel>
  )
}
