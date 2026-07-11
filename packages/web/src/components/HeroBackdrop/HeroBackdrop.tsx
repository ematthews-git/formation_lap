import { resolveHero } from '../../lib/hero'
import { useMediaQuery } from '../../lib/useMediaQuery'
import styles from './HeroBackdrop.module.css'

/**
 * Hero photo shown bleeding from the top-left, behind the header and the
 * circuit/weather row. The frosted-glass panels blur it through backdrop-filter.
 *
 * The photo tracks the featured race weekend — see `lib/hero.ts` for the
 * circuit_id → photo map (and per-photo header text tone).
 */
export function HeroBackdrop({ circuitId }: { circuitId?: string }) {
  // The ≤750px stylesheet hides the backdrop, but a hidden <img> still
  // downloads — skip rendering entirely so phones never fetch the photo.
  const isMobile = useMediaQuery('(max-width: 750px)')
  const hero = resolveHero(circuitId)
  if (isMobile || !hero) return null
  const image = hero.src

  return (
    <div className={styles.backdrop} aria-hidden="true">
      {/* key forces a fresh <img> when switching weekends so the swap isn't a flash of the old photo */}
      {/* fetchPriority: this is the page's LCP element — start it before fonts/scripts */}
      <img key={image} className={styles.photo} src={image} alt="" fetchPriority="high" />
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
