import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState } from '../common/Status'
import { prettifyCircuit } from '../../lib/format'
import styles from './LegacyArchive.module.css'

/**
 * Past winners + pole-to-win conversion. Backed by race_results, which has no
 * endpoint yet — both ship as empty states. Wire to a /results endpoint later.
 */
export function LegacyArchive({ circuitId }: { circuitId: string }) {
  return (
    <div className={styles.column}>
      <Panel>
        <PanelHeader label="LEGACY_ARCHIVE" sub={prettifyCircuit(circuitId).toUpperCase()} />
        <EmptyState
          label="ARCHIVE PENDING"
          hint="race-results refresh job + /results endpoint not yet implemented"
        />
      </Panel>

      <Panel>
        <div className={styles.poleBox}>
          <div className={styles.poleLabel}>POLE CONVERTED TO WIN</div>
          <EmptyState label="NO DATA" hint="needs historical results" />
        </div>
      </Panel>
    </div>
  )
}
