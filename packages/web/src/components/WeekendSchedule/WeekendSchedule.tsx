import { useEffect, useState } from 'react'
import type { Session } from '../../api/types'
import { CollapsiblePanel } from '../common/CollapsiblePanel'
import { EmptyState, ErrorState, LoadingState } from '../common/Status'
import { prettifyCircuit } from '../../lib/format'
import { circuitTimezone, formatClock, formatDayDate } from '../../lib/circuitTime'
import styles from './WeekendSchedule.module.css'

interface Props {
  circuitId: string | undefined
  sessions: Session[] | undefined
  loading: boolean
  /** Query failure (network/5xx) — distinct from "no schedule yet". */
  error?: boolean
}

/** Sessions that anchor the weekend get a coloured accent bar. */
function tone(name: string): 'race' | 'sprint' | undefined {
  const n = name.toLowerCase()
  if (n === 'race') return 'race'
  if (n.includes('sprint')) return 'sprint'
  return undefined
}

/** Rough running length per session (minutes), to gauge whether one is live now. */
const SESSION_MINUTES: Record<string, number> = {
  'Practice 1': 60,
  'Practice 2': 60,
  'Practice 3': 60,
  Qualifying: 60,
  'Sprint Qualifying': 45,
  Sprint: 60,
  Race: 120,
}

function isLive(session: Session, now: number): boolean {
  const start = Date.parse(session.start_time)
  if (Number.isNaN(start)) return false
  const end = start + (SESSION_MINUTES[session.name] ?? 60) * 60_000
  return now >= start && now < end
}

export function WeekendSchedule({ circuitId, sessions, loading, error }: Props) {
  const tz = circuitTimezone(circuitId)

  // Re-tick each minute so the live "NOW" badge appears/clears without a reload.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(id)
  }, [])

  return (
    <CollapsiblePanel
      label="WEEKEND_SCHEDULE"
      sub={circuitId ? prettifyCircuit(circuitId).toUpperCase() : undefined}
      meta="CIRCUIT / LOCAL"
    >
      <div className={styles.headRow}>
        <span>SESSION</span>
        <span>DATE</span>
        <span>CIRCUIT</span>
        <span>LOCAL</span>
      </div>

      {loading && !sessions ? (
        <LoadingState label="LOADING SCHEDULE" />
      ) : sessions && sessions.length > 0 ? (
        sessions.map((s) => {
          const t = tone(s.name)
          const live = isLive(s, now)
          const finishers = s.top_finishers ?? []
          return (
            <div key={s.id ?? s.session_order} className={styles.row}>
              {t && <span className={`${styles.accentBar} ${styles[t]}`} />}
              <span className={styles.session}>
                <span className={styles.sessionName}>{s.name}</span>
                {live && (
                  <span className={styles.now}>
                    <span className={styles.nowDot} />
                    NOW
                  </span>
                )}
                {finishers.length > 0 && (
                  <span className={styles.finishers}>
                    {finishers.map((f, i) => (
                      <span key={f.position}>
                        {i > 0 && ', '}
                        {f.position}.&nbsp;
                        <span className={styles.driverCode}>{f.driver_id}</span>
                      </span>
                    ))}
                  </span>
                )}
              </span>
              <span className={styles.date}>{formatDayDate(s.start_time, tz)}</span>
              <span className={styles.circuit}>{formatClock(s.start_time, tz)}</span>
              <span className={styles.local}>{formatClock(s.start_time)}</span>
            </div>
          )
        })
      ) : error ? (
        <ErrorState message="couldn't load the schedule" />
      ) : (
        <EmptyState label="NO SCHEDULE" />
      )}
    </CollapsiblePanel>
  )
}
