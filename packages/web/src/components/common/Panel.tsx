import type { CSSProperties, ReactNode } from 'react'
import styles from './Panel.module.css'

interface PanelProps {
  children: ReactNode
  /** Use the stronger border (centrepiece panels). */
  strong?: boolean
  /** Frosted-glass surface — for panels layered over the hero photo. */
  frosted?: boolean
  className?: string
  style?: CSSProperties
}

/** Bordered dark surface — the base card used across every briefing section. */
export function Panel({ children, strong, frosted, className, style }: PanelProps) {
  return (
    <div
      className={`${styles.panel} ${strong ? styles.strong : ''} ${
        frosted ? styles.frosted : ''
      } ${className ?? ''}`}
      style={style}
    >
      {children}
    </div>
  )
}
