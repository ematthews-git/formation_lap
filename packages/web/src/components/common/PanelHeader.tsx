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
}

/** The mono "LABEL // SUB ............ meta" bar atop each panel. */
export function PanelHeader({ label, sub, meta, accent }: PanelHeaderProps) {
  return (
    <div className={`${styles.header} ${accent ? styles.accentHeader : ''}`}>
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
      {meta && <span className={styles.meta}>{meta}</span>}
    </div>
  )
}
