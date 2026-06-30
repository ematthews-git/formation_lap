import type { ReactNode } from 'react'
import styles from './StatCell.module.css'

interface StatCellProps {
  label: string
  /** Big display value. Render "—" yourself when data is absent. */
  value: ReactNode
  /** Small trailing unit (°C, km, %). */
  unit?: string
  /** Override the value colour (e.g. var(--rain) for rain chance). */
  valueColor?: string
  /** Slightly smaller value type for tighter cells. */
  size?: 'lg' | 'md'
}

/** Mono label above a large Saira Condensed number — the core metric cell. */
export function StatCell({ label, value, unit, valueColor, size = 'lg' }: StatCellProps) {
  return (
    <div className={styles.cell}>
      <div className={styles.label}>{label}</div>
      <div
        className={`${styles.value} ${size === 'md' ? styles.md : ''}`}
        style={valueColor ? { color: valueColor } : undefined}
      >
        {value}
        {unit && <span className={styles.unit}>{unit}</span>}
      </div>
    </div>
  )
}
