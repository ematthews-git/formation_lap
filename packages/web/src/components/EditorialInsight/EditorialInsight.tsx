import styles from './EditorialInsight.module.css'

/**
 * Editorial storyline cards. The mockup's copy was race-specific and curated by
 * hand; there's no editorial data source yet, so we keep the three-card design
 * as labelled placeholders rather than inventing race facts. Swap the bodies in
 * once an editorial/insight source exists.
 */
const SLOTS = [1, 2, 3]

export function EditorialInsight() {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHead}>
        <span className={styles.tick} />
        <span className={styles.headLabel}>
          EDITORIAL_INSIGHT <span className={styles.slash}>//</span> BRIEFING
        </span>
      </div>
      <div className={styles.grid}>
        {SLOTS.map((n) => (
          <div key={n} className={styles.card}>
            <div className={styles.num}>{String(n).padStart(2, '0')}</div>
            <h3 className={styles.title}>Storyline pending</h3>
            <p className={styles.body}>
              Editorial briefing content is curated per race weekend and is not
              yet wired to a data source.
            </p>
          </div>
        ))}
      </div>
    </section>
  )
}
