import styles from './HeroBackdrop.module.css'

/**
 * Hero photo shown bleeding from the top-left, behind the header and the
 * circuit/weather row. The frosted-glass panels blur it through backdrop-filter.
 *
 * ── To change the photo ──
 *   Drop an image in `packages/web/public/` and point HERO_IMAGE at it
 *   (paths are served from the web root, e.g. '/my-photo.jpg').
 *
 * ── To show no photo at all ──
 *   Set HERO_IMAGE to `null`.
 */
const HERO_IMAGE: string | null = '/silverstone.jpg'

export function HeroBackdrop() {
  if (!HERO_IMAGE) return null

  return (
    <div className={styles.backdrop} aria-hidden="true">
      <img className={styles.photo} src={HERO_IMAGE} alt="" />
      {/* film grain */}
      <svg className={styles.grain} xmlns="http://www.w3.org/2000/svg">
        <filter id="flGrainHero">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.9"
            numOctaves="2"
            stitchTiles="stitch"
          />
        </filter>
        <rect width="100%" height="100%" filter="url(#flGrainHero)" />
      </svg>
      {/* scrim: keeps the title legible and dissolves the photo into the theme */}
      <div className={styles.scrim} />
    </div>
  )
}
