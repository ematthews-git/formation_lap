import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState } from '../common/Status'
import styles from './WeatherStrip.module.css'

/**
 * Weather forecast strip. There is no weather endpoint yet (the
 * weather_forecasts table has no router and the job is a skeleton), so this
 * ships as an empty state. Wire to GET /weather once that lands.
 */
export function WeatherStrip() {
  return (
    <Panel>
      <PanelHeader label="MET_FORECAST" sub="RACE_WINDOW" />
      <div className={styles.body}>
        <EmptyState
          label="FORECAST PENDING"
          hint="Open-Meteo job + /weather endpoint not yet implemented"
        />
      </div>
    </Panel>
  )
}
