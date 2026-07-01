import { useState } from 'react'
import {
  DEFAULT_SEASON,
  lookaheadWeekends,
  pickFeaturedWeekend,
  useCircuit,
  useCircuitStats,
  useDrivers,
  useCircuitPodiums,
  useLapRecord,
  useRaceResults,
  useRaceWeekends,
  useStandings,
  useStrategies,
  useWeather,
  weekendByRound,
} from './api/queries'
import { roundOverrideFromUrl } from './lib/format'
import { raceSession } from './lib/weather'
import { Header } from './components/Header/Header'
import { CircuitProfile } from './components/CircuitProfile/CircuitProfile'
import { WeatherStrip } from './components/WeatherStrip/WeatherStrip'
import { TyreStrategy } from './components/TyreStrategy/TyreStrategy'
import { DriverForm } from './components/DriverForm/DriverForm'
import { PastResults } from './components/PastResults/PastResults'
import { EditorialInsight } from './components/EditorialInsight/EditorialInsight'
import { LoadingState, ErrorState } from './components/common/Status'
import styles from './App.module.css'

const SEASON = DEFAULT_SEASON

export default function App() {
  // A round the user has clicked into via the lookahead; null = the upcoming race.
  const [selectedRound, setSelectedRound] = useState<number | undefined>(
    roundOverrideFromUrl(),
  )

  const weekends = useRaceWeekends(SEASON)
  const upcoming = pickFeaturedWeekend(weekends.data)
  const lookahead = lookaheadWeekends(weekends.data, 3)
  const featured =
    selectedRound != null
      ? (weekendByRound(weekends.data, selectedRound) ?? upcoming)
      : upcoming

  const onSelectRound = (round: number) =>
    // Click the active lookahead race again to return to the upcoming one.
    setSelectedRound((cur) => (cur === round ? undefined : round))

  const circuit = useCircuit(featured?.circuit_id)
  const lapRecord = useLapRecord(featured?.circuit_id)
  const stats = useCircuitStats(featured?.circuit_id, SEASON)
  const strategies = useStrategies(SEASON, featured?.round_number)
  const weather = useWeather(SEASON, featured?.round_number)
  const drivers = useDrivers(SEASON)
  const standings = useStandings(SEASON)
  const raceResults = useRaceResults(SEASON)
  const podiums = useCircuitPodiums(featured?.circuit_id)

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
      <Header
        weekend={featured}
        circuit={circuit.data}
        totalRounds={totalRounds}
        raceWeather={raceSession(weather.data)}
        lookahead={lookahead}
        activeRound={featured.round_number}
        onSelectRound={onSelectRound}
      />

      <main className={styles.main}>
        <section className={styles.splitWide}>
          <CircuitProfile
            circuit={circuit.data}
            circuitLoading={circuit.isLoading}
            lapRecord={lapRecord.data}
            lapRecordLoading={lapRecord.isLoading}
          />
          <WeatherStrip weather={weather.data} weatherLoading={weather.isLoading} />
        </section>

        <TyreStrategy
          weekend={featured}
          stats={stats.data}
          statsLoading={stats.isLoading}
          strategies={strategies.data}
          strategiesLoading={strategies.isLoading}
        />

        <section className={`${styles.splitWide} ${styles.alignStart}`}>
          <DriverForm
            drivers={drivers.data}
            driversLoading={drivers.isLoading}
            driversError={drivers.isError}
            standings={standings.data}
            raceResults={raceResults.data}
          />
          <PastResults
            circuitId={featured.circuit_id}
            podiums={podiums.data}
            loading={podiums.isLoading}
          />
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
