import type { CircuitStats, RaceWeekend } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState, LoadingState } from '../common/Status'
import { prettifyCircuit } from '../../lib/format'
import styles from './TyreStrategy.module.css'

interface Props {
  weekend: RaceWeekend
  stats: CircuitStats | null | undefined
  statsLoading: boolean
}

const COMPOUNDS = [
  { key: 'hard', name: 'Hard', desc: 'DURABLE · LOW DEG', color: 'var(--hard)' },
  { key: 'medium', name: 'Medium', desc: 'BALANCED · GO-TO', color: 'var(--gold)' },
  { key: 'soft', name: 'Soft', desc: 'PEAK GRIP · QUALI', color: 'var(--soft)' },
] as const

export function TyreStrategy({ weekend, stats, statsLoading }: Props) {
  const code = {
    hard: weekend.hard_compound,
    medium: weekend.medium_compound,
    soft: weekend.soft_compound,
  }
  const allocation = `PIRELLI ${weekend.soft_compound}–${weekend.hard_compound}`

  return (
    <Panel strong>
      <PanelHeader
        accent
        label="TYRE_STRATEGY"
        sub={prettifyCircuit(weekend.circuit_id).toUpperCase()}
        meta={allocation}
      />

      <div className={styles.topRow}>
        {/* compounds — live from the weekend allocation */}
        <div className={styles.compounds}>
          <div className={styles.sectionLabel}>AVAILABLE COMPOUNDS</div>
          <div className={styles.compoundList}>
            {COMPOUNDS.map((c) => (
              <div key={c.key} className={styles.compound}>
                <div className={styles.compoundChip} style={{ borderColor: c.color, color: c.color }}>
                  {code[c.key]}
                </div>
                <div>
                  <div className={styles.compoundName}>{c.name}</div>
                  <div className={styles.compoundDesc}>{c.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* undercut window — from circuit stats (empty until recomputed) */}
        <div className={styles.undercut}>
          <div className={styles.sectionLabel}>UNDERCUT WINDOW</div>
          {statsLoading ? (
            <LoadingState />
          ) : stats ? (
            <>
              <div className={styles.bigValueRow}>
                <span className={styles.bigValue}>{stats.undercut_strength.toFixed(1)}</span>
                <span className={styles.bigUnit}>s</span>
                <span className={styles.bigCaption}>GAP THRESHOLD</span>
              </div>
              <div className={styles.miniStats}>
                <Mini label="PIT LOSS" value={`${stats.pit_loss_normal.toFixed(1)}s`} />
                <Mini
                  label="FAVOURS"
                  value={stats.undercut_strength >= stats.overcut_strength ? 'UNDERCUT' : 'OVERCUT'}
                />
              </div>
            </>
          ) : (
            <EmptyState hint="circuit-stats recompute job not yet run" />
          )}
        </div>

        {/* safety car probability — from circuit stats */}
        <div className={styles.safetyCar}>
          <div className={styles.sectionLabel}>SAFETY CAR PROBABILITY</div>
          {statsLoading ? (
            <LoadingState />
          ) : stats ? (
            <div>
              <div className={styles.scValueRow}>
                <span className={styles.scValue}>{stats.sc_probability}</span>
                <span className={styles.scUnit}>%</span>
              </div>
              <div className={styles.scBar}>
                <div className={styles.scBarFill} style={{ width: `${stats.sc_probability}%` }} />
              </div>
            </div>
          ) : (
            <EmptyState hint="circuit-stats recompute job not yet run" />
          )}
        </div>
      </div>

      {/* stint timeline — strategies have no endpoint yet */}
      <div className={styles.stintArea}>
        <div className={styles.sectionLabel}>STINT PLAN</div>
        <EmptyState
          label="STRATEGY MODEL PENDING"
          hint="strategies generate job + /strategies endpoint not yet implemented"
        />
      </div>
    </Panel>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className={styles.miniLabel}>{label}</div>
      <div className={styles.miniValue}>{value}</div>
    </div>
  )
}
