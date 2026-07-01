import type { RaceResult } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState, LoadingState } from '../common/Status'
import { prettifyCircuit, teamColorVar } from '../../lib/format'
import styles from './PastResults.module.css'

interface RaceGroup {
  season: number
  round: number
  podium: RaceResult[]
}

/** Group the flat (already season-desc, position-asc) rows into races. */
function groupRaces(results: RaceResult[]): RaceGroup[] {
  const groups: RaceGroup[] = []
  for (const r of results) {
    const last = groups[groups.length - 1]
    if (last && last.season === r.season && last.round === r.round_number) {
      last.podium.push(r)
    } else {
      groups.push({ season: r.season, round: r.round_number, podium: [r] })
    }
  }
  return groups
}

function surname(driverId: string): string {
  return driverId.charAt(0).toUpperCase() + driverId.slice(1)
}

interface Props {
  circuitId: string
  podiums: RaceResult[] | undefined
  loading: boolean
}

export function PastResults({ circuitId, podiums, loading }: Props) {
  const races = podiums ? groupRaces(podiums) : []

  return (
    <Panel>
      <PanelHeader
        label="PAST_RESULTS"
        sub={prettifyCircuit(circuitId).toUpperCase()}
        meta={races.length > 0 ? `LAST ${races.length}` : undefined}
      />
      {loading && !podiums ? (
        <LoadingState label="LOADING RESULTS" />
      ) : races.length > 0 ? (
        <div>
          {races.map((race) => {
            const [winner, ...runners] = race.podium
            return (
              <div key={`${race.season}-${race.round}`} className={styles.race}>
                <div className={styles.season}>’{String(race.season).slice(-2)}</div>
                <div className={styles.content}>
                  <div className={styles.winnerRow}>
                    <span className={styles.winner}>{surname(winner.driver_id)}</span>
                    <span className={styles.team}>
                      <span
                        className={styles.teamDot}
                        style={{ background: teamColorVar(winner.team) }}
                      />
                      {winner.team}
                    </span>
                  </div>
                  {runners.length > 0 && (
                    <div className={styles.runners}>
                      {runners
                        .map((r) => `${r.position}. ${surname(r.driver_id)}`)
                        .join(', ')}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <EmptyState
          label="NO PAST RESULTS"
          hint="new venue or no race history at this circuit"
        />
      )}
    </Panel>
  )
}
