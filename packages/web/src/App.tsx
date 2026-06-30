import {
  DEFAULT_SEASON,
  pickFeaturedWeekend,
  useCircuit,
  useCircuitStats,
  useDrivers,
  useLapRecord,
  useRaceWeekends,
  useStandings,
} from './api/queries'
import { roundOverrideFromUrl } from './lib/format'
import { Header } from './components/Header/Header'
import { CircuitProfile } from './components/CircuitProfile/CircuitProfile'
import { WeatherStrip } from './components/WeatherStrip/WeatherStrip'
import { TyreStrategy } from './components/TyreStrategy/TyreStrategy'
import { DriverForm } from './components/DriverForm/DriverForm'
import { LegacyArchive } from './components/LegacyArchive/LegacyArchive'
import { EditorialInsight } from './components/EditorialInsight/EditorialInsight'
import { LoadingState, ErrorState } from './components/common/Status'
import styles from './App.module.css'

const SEASON = DEFAULT_SEASON

export default function App() {
  const roundOverride = roundOverrideFromUrl()

  const weekends = useRaceWeekends(SEASON)
  const featured = pickFeaturedWeekend(weekends.data, roundOverride)

  const circuit = useCircuit(featured?.circuit_id)
  const lapRecord = useLapRecord(featured?.circuit_id)
  const stats = useCircuitStats(featured?.circuit_id, SEASON)
  const drivers = useDrivers(SEASON)
  const standings = useStandings(SEASON)

  if (weekends.isError) {
    return (
      <div className={styles.fullState}>
        <ErrorState
          message={`Could not reach the API — is uvicorn running on :8000? (${(weekends.error as Error).message})`}
        />
      </div>
    )
  }

  if (!featured) {
    return (
      <div className={styles.fullState}>
        {weekends.isLoading ? (
          <LoadingState label="LOADING CALENDAR" />
        ) : (
          <ErrorState
            message={`No race weekends found for ${SEASON}. Seed them: formation-data weekends seed --season ${SEASON}`}
          />
        )}
      </div>
    )
  }

  const totalRounds = weekends.data
    ? Math.max(...weekends.data.map((w) => w.round_number))
    : featured.round_number

  const updated = new Date().toUTCString().replace('GMT', 'UTC')

  return (
    <div className={styles.page}>
      <Header weekend={featured} circuit={circuit.data} totalRounds={totalRounds} />

      <main className={styles.main}>
        <section className={styles.splitWide}>
          <CircuitProfile
            circuit={circuit.data}
            circuitLoading={circuit.isLoading}
            lapRecord={lapRecord.data}
            lapRecordLoading={lapRecord.isLoading}
          />
          <WeatherStrip />
        </section>

        <TyreStrategy weekend={featured} stats={stats.data} statsLoading={stats.isLoading} />

        <section className={`${styles.splitWide} ${styles.alignStart}`}>
          <DriverForm
            drivers={drivers.data}
            driversLoading={drivers.isLoading}
            driversError={drivers.isError}
            standings={standings.data}
          />
          <LegacyArchive circuitId={featured.circuit_id} />
        </section>

        <EditorialInsight />

        <footer className={styles.footer}>
          <span>FORMATION LAP · LIVE API · STRATEGY MODELLED FOR ILLUSTRATION</span>
          <span>BRIEFING RENDERED {updated}</span>
        </footer>
      </main>
    </div>
  )
}
