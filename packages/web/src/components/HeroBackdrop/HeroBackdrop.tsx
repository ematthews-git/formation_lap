import styles from './HeroBackdrop.module.css'

/**
 * Hero photo shown bleeding from the top-left, behind the header and the
 * circuit/weather row. The frosted-glass panels blur it through backdrop-filter.
 *
 * The photo tracks the featured race weekend: each circuit maps to an image in
 * `packages/web/public/`, keyed by `circuit_id`.
 *
 * ── To add a photo for a circuit ──
 *   Drop `<name>.jpg` in `packages/web/public/` and add a
 *   `<circuit_id>: '/<name>.jpg'` entry to HERO_IMAGES below.
 *
 * ── Circuits without their own photo ──
 *   Fall back to HERO_FALLBACK. Set it to `null` to show no backdrop for them.
 */
const HERO_IMAGES: Record<string, string> = {
  silverstone: '/silverstone.jpg',
  spa: '/spa.jpg',
  hungaroring: '/hungary.jpg',
  monza: '/monza.jpg',
  baku: '/baku.jpg',
  singapore: '/singapore.jpg',
  austin: '/austin.jpg',
  abu_dhabi: '/abu-dhabi.jpg',
}

const HERO_FALLBACK: string | null = '/silverstone.jpg'

export function HeroBackdrop({ circuitId }: { circuitId?: string }) {
  const image = (circuitId && HERO_IMAGES[circuitId]) || HERO_FALLBACK
  if (!image) return null

  return (
    <div className={styles.backdrop} aria-hidden="true">
      {/* key forces a fresh <img> when switching weekends so the swap isn't a flash of the old photo */}
      <img key={image} className={styles.photo} src={image} alt="" />
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
