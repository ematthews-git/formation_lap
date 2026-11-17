import type { CSSProperties } from 'react'
import { resolveHero } from '../../lib/hero'
import { useMediaQuery } from '../../lib/useMediaQuery'
import styles from './HeroBackdrop.module.css'

/**
 * Hero photo shown bleeding from the top-left, behind the header and the
 * circuit/weather row. The frosted-glass panels blur it through backdrop-filter.
 *
 * The photo tracks the featured race weekend — see `lib/hero.ts` for the
 * circuit_id → photo map (and per-photo header text tone).
 *
 * `lens` renders a second copy for a liquid-glass panel to refract, scrim
 * included so the glass matches the page's exposure, positioned by the caller
 * to line up exactly with the page copy (found through `data-hero="page"`).
 */
export function HeroBackdrop({
  circuitId,
  lens,
  style,
}: {
  circuitId?: string
  lens?: boolean
  style?: CSSProperties
}) {
  // The ≤750px stylesheet hides the backdrop, but a hidden <img> still
  // downloads — skip rendering entirely so phones never fetch the photo.
  const isMobile = useMediaQuery('(max-width: 750px)')
  const hero = resolveHero(circuitId)
  if (isMobile || !hero) return null
  const image = hero.src

  return (
    <div
      className={`${styles.backdrop} ${lens ? styles.lens : ''}`}
      style={style}
      data-hero={lens ? undefined : 'page'}
      aria-hidden="true"
    >
      {/* key forces a fresh <img> when switching weekends so the swap isn't a flash of the old photo */}
      {/* fetchPriority: this is the page's LCP element — start it before fonts/scripts */}
      <img
        key={image}
        className={styles.photo}
        src={image}
        alt=""
        fetchPriority={lens ? undefined : 'high'}
      />
      {/* film grain */}
      <svg className={styles.grain} xmlns="http://www.w3.org/2000/svg">
        <filter id={lens ? 'flGrainLens' : 'flGrainHero'}>
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.9"
            numOctaves="2"
            stitchTiles="stitch"
          />
        </filter>
        <rect width="100%" height="100%" filter={lens ? 'url(#flGrainLens)' : 'url(#flGrainHero)'} />
      </svg>
      {/* scrim: keeps the title legible and dissolves the photo into the theme */}
      <div className={styles.scrim} />
    </div>
  )
}
