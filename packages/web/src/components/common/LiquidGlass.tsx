import { useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { resolveHero } from '../../lib/hero'
import { buildLiquidGlassMaps } from '../../lib/liquidGlass'
import { HeroBackdrop } from '../HeroBackdrop/HeroBackdrop'
import { liftClass, useLift } from './useLift'
import styles from './LiquidGlass.module.css'

/** Card corner radius — matches the weather card — and the refracting rim, px. */
const RADIUS = 18
const BEZEL = 30
/** Strongest shift at the very edge, px (feDisplacementMap scale = 2 × shift). */
const REFRACTION = 26
/** Barely any frost: this is clear glass, the photo should stay sharp. */
const FROST = 1.4

interface Box {
  w: number
  h: number
  /** The page hero photo's rect, relative to this card. */
  hero: { left: number; top: number; width: number; height: number } | null
}

const sameBox = (a: Box | null, b: Box) =>
  !!a &&
  a.w === b.w &&
  a.h === b.h &&
  a.hero?.left === b.hero?.left &&
  a.hero?.top === b.hero?.top &&
  a.hero?.width === b.hero?.width &&
  a.hero?.height === b.hero?.height

/** Position in the page from the layout box, ignoring any CSS transforms. */
function pageOffset(el: HTMLElement): { left: number; top: number } {
  let left = 0
  let top = 0
  for (let n: HTMLElement | null = el; n; n = n.offsetParent as HTMLElement | null) {
    left += n.offsetLeft
    top += n.offsetTop
  }
  return { left, top }
}

/**
 * A clear liquid-glass card over the hero photo.
 *
 * Rather than a `backdrop-filter` (SVG backdrop filters only render in
 * Chromium), the card holds its own copy of the hero photo, lined up pixel for
 * pixel with the one on the page, and bends that copy with an ordinary CSS
 * `filter: url(#…)` — refraction at the rim plus a specular edge — which works
 * in every engine. Where there's no photo (phones, or a circuit without one) it
 * refracts a solid colour field instead, so the card still has a bold surface.
 *
 * The copy keeps the page's scrim, so the glass never lightens the photo; a
 * thin dark tint on top leaves it the same or a touch darker, under white ink.
 */
export function LiquidGlass({
  circuitId,
  label,
  className,
  children,
}: {
  circuitId?: string
  /** Accessible name for the card region. */
  label: string
  className?: string
  children: ReactNode
}) {
  const ref = useRef<HTMLElement>(null)
  const filterId = 'lg' + useId().replace(/[^\w-]/g, '')
  const [box, setBox] = useState<Box | null>(null)
  useLift(ref)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      // Layout offsets, not getBoundingClientRect: the card lifts and tilts on
      // hover, and a measurement taken mid-hover must not bake that in.
      const c = pageOffset(el)
      const heroEl = document.querySelector<HTMLElement>('[data-hero="page"]')
      const h = heroEl ? pageOffset(heroEl) : null
      const next: Box = {
        w: Math.round(el.offsetWidth),
        h: Math.round(el.offsetHeight),
        hero:
          h && heroEl
            ? {
                left: h.left - c.left,
                top: h.top - c.top,
                width: heroEl.offsetWidth,
                height: heroEl.offsetHeight,
              }
            : null,
      }
      setBox((prev) => (sameBox(prev, next) ? prev : next))
    }
    measure()
    // The card can move against the photo without either resizing (the header
    // above grows when its data lands), so watch the page height too.
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    ro.observe(document.body)
    const heroEl = document.querySelector('[data-hero="page"]')
    if (heroEl) ro.observe(heroEl)
    window.addEventListener('resize', measure)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [circuitId])

  // Only the card's size changes the maps; a move against the photo doesn't.
  const w = box?.w
  const h = box?.h
  const maps = useMemo(
    () => (w && h ? buildLiquidGlassMaps({ width: w, height: h, radius: RADIUS, bezel: BEZEL }) : null),
    [w, h],
  )

  const hero = box?.hero ? resolveHero(circuitId) : null

  return (
    <section
      ref={ref}
      aria-label={label}
      className={`${styles.glass} ${liftClass} ${className ?? ''}`}
    >
      <div
        className={styles.lens}
        style={maps ? { filter: `url(#${filterId})` } : undefined}
        aria-hidden="true"
      >
        {hero && box?.hero ? (
          <HeroBackdrop circuitId={circuitId} lens style={box.hero} />
        ) : (
          <div className={styles.field} />
        )}
      </div>
      <div className={styles.tint} aria-hidden="true" />
      <div className={styles.rim} aria-hidden="true" />

      {maps && box && (
        <svg className={styles.defs} aria-hidden="true" focusable="false">
          <filter
            id={filterId}
            x="0"
            y="0"
            width={box.w}
            height={box.h}
            filterUnits="userSpaceOnUse"
            primitiveUnits="userSpaceOnUse"
            colorInterpolationFilters="sRGB"
          >
            <feGaussianBlur in="SourceGraphic" stdDeviation={FROST} result="frost" />
            <feImage
              href={maps.displacement}
              x="0"
              y="0"
              width={box.w}
              height={box.h}
              preserveAspectRatio="none"
              result="map"
            />
            <feDisplacementMap
              in="frost"
              in2="map"
              scale={REFRACTION * 2}
              xChannelSelector="R"
              yChannelSelector="G"
              result="refracted"
            />
            <feColorMatrix in="refracted" type="saturate" values="1.1" result="glass" />
            <feImage
              href={maps.specular}
              x="0"
              y="0"
              width={box.w}
              height={box.h}
              preserveAspectRatio="none"
              result="rimRaw"
            />
            <feComponentTransfer in="rimRaw" result="rim">
              <feFuncA type="linear" slope="0.05" />
            </feComponentTransfer>
            <feComposite in="rim" in2="glass" operator="over" />
          </filter>
        </svg>
      )}

      <div className={styles.content}>{children}</div>
    </section>
  )
}
