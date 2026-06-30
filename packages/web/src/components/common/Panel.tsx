import type { CSSProperties, ReactNode } from 'react'
import styles from './Panel.module.css'

interface PanelProps {
  children: ReactNode
  /** Use the stronger border (centrepiece panels). */
  strong?: boolean
  className?: string
  style?: CSSProperties
}

/** Bordered dark surface — the base card used across every briefing section. */
export function Panel({ children, strong, className, style }: PanelProps) {
  return (
    <div
      className={`${styles.panel} ${strong ? styles.strong : ''} ${className ?? ''}`}
      style={style}
    >
      {children}
    </div>
  )
}
