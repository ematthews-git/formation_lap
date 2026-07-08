import { useState } from 'react'
import { Analytics } from '@vercel/analytics/react'
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
  useSessions,
  useSimStats,
  useSimStrategies,
  useStandings,
  useStrategies,
  useWeather,
  weekendByRound,
} from './api/queries'
import { roundOverrideFromUrl } from './lib/format'
import { raceSession } from './lib/weather'
import { HeroBackdrop } from './components/HeroBackdrop/HeroBackdrop'
import { TopBar } from './components/TopBar/TopBar'
import { Header } from './components/Header/Header'
import { CircuitProfile } from './components/CircuitProfile/CircuitProfile'
import { WeatherStrip } from './components/WeatherStrip/WeatherStrip'
import { StrategyEngine } from './components/StrategyEngine/StrategyEngine'
import { DriverForm } from './components/DriverForm/DriverForm'
import { ConstructorStandings } from './components/ConstructorStandings/ConstructorStandings'
import { PastResults } from './components/PastResults/PastResults'
import { WeekendSchedule } from './components/WeekendSchedule/WeekendSchedule'
import { Footer } from './components/Footer/Footer'
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
  // The upcoming race plus the next few, in calendar order — each is a selector button.
  const raceOptions = upcoming ? [upcoming, ...lookahead] : lookahead
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
  const simStrategies = useSimStrategies(SEASON, featured?.round_number)
  const simStats = useSimStats(SEASON, featured?.round_number)
  // Last season's engine parameters — the fallback when this season's sim hasn't
  // run yet. No previous-season rows exist yet, so this resolves empty for now.
  const simStatsLastSeason = useSimStats(SEASON - 1, featured?.round_number)
  const weather = useWeather(SEASON, featured?.round_number)
  const sessions = useSessions(SEASON, featured?.round_number)
  const drivers = useDrivers(SEASON)
  const standings = useStandings(SEASON)
  const constructorStandings = useStandings(SEASON, 'constructor')
  // Previous season's final standings feed the "LAST" column; derived from SEASON
  // so it rolls over cleanly when the app advances to the next season.
  const lastSeasonConstructors = useStandings(SEASON - 1, 'constructor')
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

  return (
    <div className={styles.page}>
      <TopBar
        raceWeather={raceSession(weather.data)}
        races={raceOptions}
        activeRound={featured.round_number}
        onSelectRound={onSelectRound}
      />

      <div className={styles.stage}>
        <HeroBackdrop circuitId={featured.circuit_id} />
        <Header
          weekend={featured}
          circuit={circuit.data}
          totalRounds={totalRounds}
        />

        <main className={styles.main}>
        <section className={`${styles.splitWide} ${styles.profileRow}`}>
          <CircuitProfile
            circuit={circuit.data}
            circuitLoading={circuit.isLoading}
            lapRecord={lapRecord.data}
            lapRecordLoading={lapRecord.isLoading}
          />
          <WeatherStrip weather={weather.data} weatherLoading={weather.isLoading} />
        </section>

        <StrategyEngine
          weekend={featured}
          stats={stats.data}
          statsLoading={stats.isLoading}
          historicalStrategies={strategies.data}
          historicalStrategiesLoading={strategies.isLoading}
          simStrategies={simStrategies.data}
          simStrategiesLoading={simStrategies.isLoading}
          simStats={simStats.data}
          simStatsLoading={simStats.isLoading}
          fallbackStats={simStatsLastSeason.data}
          fallbackStatsLoading={simStatsLastSeason.isLoading}
        />

        <section className={`${styles.splitWide} ${styles.alignStart}`}>
          <WeekendSchedule
            circuitId={featured.circuit_id}
            sessions={sessions.data}
            loading={sessions.isLoading}
          />
          <PastResults
            circuitId={featured.circuit_id}
            podiums={podiums.data}
            loading={podiums.isLoading}
          />
        </section>

        <section className={`${styles.splitWide} ${styles.alignStart}`}>
          <DriverForm
            drivers={drivers.data}
            driversLoading={drivers.isLoading}
            driversError={drivers.isError}
            standings={standings.data}
            raceResults={raceResults.data}
          />
          <ConstructorStandings
            standings={constructorStandings.data}
            lastSeason={lastSeasonConstructors.data}
            loading={constructorStandings.isLoading}
            error={constructorStandings.isError}
          />
        </section>
        </main>
      </div>
      <Footer />
      <Analytics />
    </div>
  )
}
