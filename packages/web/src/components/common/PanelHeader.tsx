import type { ReactNode } from 'react'
import styles from './PanelHeader.module.css'

interface PanelHeaderProps {
  /** Mono code label, e.g. "TRK_PROFILE". */
  label: string
  /** Optional second segment after a dim "//", e.g. "SILVERSTONE". */
  sub?: string
  /** Optional right-aligned meta text. */
  meta?: ReactNode
  /** Show the red accent tick (centrepiece sections). */
  accent?: boolean
  /** Render as a tappable toggle with a chevron (used by CollapsiblePanel). */
  collapsible?: boolean
  /** Current open state — drives the chevron rotation and aria-expanded. */
  open?: boolean
  onToggle?: () => void
}

function Chevron({ open }: { open?: boolean }) {
  return (
    <span
      className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}
      aria-hidden="true"
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
        <path d="M6 9l6 6 6-6" />
      </svg>
    </span>
  )
}

/** The mono "LABEL // SUB ............ meta" bar atop each panel. */
export function PanelHeader({
  label,
  sub,
  meta,
  accent,
  collapsible,
  open,
  onToggle,
}: PanelHeaderProps) {
  const left = (
    <div className={styles.left}>
      {accent && <span className={styles.tick} />}
      <span className={styles.label}>
        {label}
        {sub && (
          <>
            {' '}
            <span className={styles.slash}>//</span> {sub}
          </>
        )}
      </span>
    </div>
  )

  if (collapsible) {
    return (
      <button
        type="button"
        className={`${styles.header} ${styles.headerButton} ${accent ? styles.accentHeader : ''}`}
        onClick={onToggle}
        aria-expanded={open}
      >
        {left}
        <span className={styles.rightGroup}>
          {meta && <span className={styles.meta}>{meta}</span>}
          <Chevron open={open} />
        </span>
      </button>
    )
  }

  return (
    <div className={`${styles.header} ${accent ? styles.accentHeader : ''}`}>
      {left}
      {meta && <span className={styles.meta}>{meta}</span>}
    </div>
  )
}
