import { useState, type ReactNode } from 'react'
import { Panel } from './Panel'
import { PanelHeader } from './PanelHeader'
import { useMediaQuery } from '../../lib/useMediaQuery'
import styles from './CollapsiblePanel.module.css'

interface Props {
  /** Mono code label, e.g. "WEEKEND_SCHEDULE". */
  label: string
  /** Optional second segment after a dim "//". */
  sub?: string
  /** Optional right-aligned meta text. */
  meta?: ReactNode
  /** Start expanded even on mobile (default: collapsed). */
  defaultOpen?: boolean
  /** Frosted-glass surface — for panels layered over the hero photo. */
  frosted?: boolean
  className?: string
  children: ReactNode
}

/**
 * A Panel whose body collapses on mobile (≤600px) behind a tappable header,
 * sliding open via a grid-rows transition; while open the body scrolls
 * horizontally so wide tables stay contained within the panel. Above 600px it
 * renders as a plain, always-open Panel with no toggle — desktop is unchanged.
 */
export function CollapsiblePanel({
  label,
  sub,
  meta,
  defaultOpen = false,
  frosted,
  className,
  children,
}: Props) {
  const isMobile = useMediaQuery('(max-width: 750px)')
  const [open, setOpen] = useState(defaultOpen)

  if (!isMobile) {
    return (
      <Panel frosted={frosted} className={className}>
        <PanelHeader label={label} sub={sub} meta={meta} />
        {children}
      </Panel>
    )
  }

  return (
    <Panel frosted={frosted} className={className}>
      <PanelHeader
        label={label}
        sub={sub}
        meta={meta}
        collapsible
        open={open}
        onToggle={() => setOpen((o) => !o)}
      />
      <div className={`${styles.region} ${open ? styles.open : ''}`}>
        <div className={styles.regionInner}>
          <div className={styles.scroll}>{children}</div>
        </div>
      </div>
    </Panel>
  )
}
