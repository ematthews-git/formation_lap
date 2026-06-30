import styles from './Status.module.css'

/** Shown while a query is in flight. */
export function LoadingState({ label = 'LOADING' }: { label?: string }) {
  return (
    <div className={`${styles.status} ${styles.loading}`}>
      <span className={styles.dot} />
      {label}…
    </div>
  )
}

/**
 * Shown when a query succeeded but there's no data yet — the common case for
 * sections whose backend job/endpoint isn't implemented (live-API-only mode).
 */
export function EmptyState({
  label = 'NO DATA YET',
  hint,
}: {
  label?: string
  hint?: string
}) {
  return (
    <div className={`${styles.status} ${styles.empty}`}>
      <span className={styles.label}>{label}</span>
      {hint && <span className={styles.hint}>{hint}</span>}
    </div>
  )
}

/** Shown when a query errored (network / 5xx). */
export function ErrorState({ message }: { message?: string }) {
  return (
    <div className={`${styles.status} ${styles.error}`}>
      <span className={styles.label}>FEED ERROR</span>
      {message && <span className={styles.hint}>{message}</span>}
    </div>
  )
}
