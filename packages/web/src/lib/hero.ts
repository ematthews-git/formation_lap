/**
 * Hero photo shown behind the header + circuit/weather row, keyed by circuit_id.
 *
 * `tone` controls the header text colour over that photo:
 *   'dark'  → black text  (use for bright/daylight photos)
 *   'light' → white text  (use for dark/night photos)
 *
 * ── To add a photo for a circuit ──
 *   Drop `<name>.webp` in `packages/web/public/`, add a
 *   `<circuit_id>: { src: '/<name>.webp', tone: 'dark' | 'light' }` entry below,
 *   and flip `tone` to whichever reads better against that photo.
 *
 * ── Circuits without their own photo ──
 *   Fall back to HERO_FALLBACK. Set it to `null` to show no backdrop for them.
 */
export type HeroTextTone = 'dark' | 'light'

export interface Hero {
  src: string
  tone: HeroTextTone
}

const HERO_IMAGES: Record<string, Hero> = {
  silverstone: { src: '/silverstone.webp', tone: 'dark' },
  spa: { src: '/spa.webp', tone: 'light' },
  hungaroring: { src: '/hungary.webp', tone: 'light' },
  monza: { src: '/monza.webp', tone: 'light' },
  baku: { src: '/baku.webp', tone: 'dark' },
  singapore: { src: '/singapore.webp', tone: 'dark' },
  austin: { src: '/austin.webp', tone: 'dark' },
  abu_dhabi: { src: '/abu-dhabi.webp', tone: 'dark' },
}

const HERO_FALLBACK: Hero | null = HERO_IMAGES.silverstone

/** The photo + text tone for a circuit, or null when there's no backdrop. */
export function resolveHero(circuitId?: string): Hero | null {
  return (circuitId && HERO_IMAGES[circuitId]) || HERO_FALLBACK
}
