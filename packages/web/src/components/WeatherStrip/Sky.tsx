import { useId, useMemo } from 'react'
import type { SkyKind } from '../../lib/weather'
import styles from './Sky.module.css'

/**
 * Full-bleed weather backdrop for the forecast card, drawn procedurally in SVG
 * so there are no image assets to ship: a flat saturated colour with film
 * grain (clear / heat), fractal-noise clouds (cloud / overcast), or raindrops
 * on a pane of glass over a blurred sky (rain). Static by design — no motion.
 */
export function Sky({ kind }: { kind: SkyKind }) {
  // useId output contains characters that break url(#…) references.
  const uid = 'sky' + useId().replace(/[^\w-]/g, '')
  return (
    <div className={`${styles.sky} ${styles[kind]}`} aria-hidden="true">
      {kind === 'cloud' && <Clouds uid={uid} dense={false} />}
      {kind === 'overcast' && <Clouds uid={uid} dense />}
      {kind === 'rain' && <RainGlass uid={uid} />}
      <Grain uid={uid} strong={kind === 'clear' || kind === 'heat'} />
    </div>
  )
}

function Grain({ uid, strong }: { uid: string; strong: boolean }) {
  const id = `${uid}-grain`
  return (
    <svg className={`${styles.layer} ${styles.grain} ${strong ? styles.grainStrong : ''}`}>
      <filter id={id}>
        <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="3" stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width="100%" height="100%" filter={`url(#${id})`} />
    </svg>
  )
}

/**
 * Two passes over the same fractal noise: a grey "shade" pass with slightly
 * wider coverage, then a white pass nudged up-left on top of it, which leaves
 * grey undersides on every cloud. Coverage is the alpha threshold on the noise.
 */
function Clouds({ uid, dense }: { uid: string; dense: boolean }) {
  const id = `${uid}-clouds`
  const slope = 3
  // Noise above `start` begins to show; lower start → more of the sky covered.
  const start = dense ? 0.4 : 0.5
  const offset = slope * start
  const shade = dense ? '0.42 0.47 0.55' : '0.6 0.66 0.76'
  const [r, g, b] = shade.split(' ')
  return (
    <svg className={styles.layer}>
      <filter
        id={id}
        x="0"
        y="0"
        width="100%"
        height="100%"
        colorInterpolationFilters="sRGB"
      >
        <feTurbulence
          type="fractalNoise"
          baseFrequency={dense ? '0.007 0.012' : '0.0055 0.0095'}
          numOctaves="5"
          seed={dense ? 4 : 11}
          result="noise"
        />
        <feColorMatrix
          in="noise"
          type="matrix"
          values={`0 0 0 0 ${r}  0 0 0 0 ${g}  0 0 0 0 ${b}  ${slope} 0 0 0 ${-(offset - 0.15)}`}
          result="shade"
        />
        <feColorMatrix
          in="noise"
          type="matrix"
          values={`0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  ${slope} 0 0 0 ${-offset}`}
          result="lightRaw"
        />
        <feOffset in="lightRaw" dx="-5" dy="-9" result="lightShift" />
        <feGaussianBlur in="lightShift" stdDeviation="1.2" result="light" />
        <feMerge>
          <feMergeNode in="shade" />
          <feMergeNode in="light" />
        </feMerge>
      </filter>
      <rect width="100%" height="100%" filter={`url(#${id})`} />
    </svg>
  )
}

/** Small deterministic PRNG so the droplets land in the same places every render. */
function mulberry32(seed: number) {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const VB_W = 480
const VB_H = 320

interface Drop {
  x: number
  y: number
  r: number
  e: number // vertical stretch
}

interface Trail {
  d: string
  end: Drop
}

function makeRain(): { drops: Drop[]; trails: Trail[] } {
  const rand = mulberry32(2026)
  const drops: Drop[] = []
  for (let i = 0; i < 190; i++) {
    // Cubed so most drops are fine mist and a few are fat beads.
    const r = 0.6 + 6.5 * rand() ** 3
    drops.push({ x: rand() * VB_W, y: rand() * VB_H, r, e: 1 + rand() * 0.3 })
  }
  const trails: Trail[] = []
  for (let i = 0; i < 7; i++) {
    const x0 = 20 + rand() * (VB_W - 40)
    const y0 = -10 + rand() * 60
    const len = 70 + rand() * 180
    let d = `M${x0.toFixed(1)} ${y0.toFixed(1)}`
    let x = x0
    let y = y0
    for (let s = 0; s < 6; s++) {
      y += len / 6
      x += (rand() - 0.5) * 7
      d += ` L${x.toFixed(1)} ${y.toFixed(1)}`
    }
    trails.push({ d, end: { x, y: y + 2, r: 4 + rand() * 3, e: 1.3 } })
  }
  return { drops, trails }
}

function RainGlass({ uid }: { uid: string }) {
  const { drops, trails } = useMemo(makeRain, [])
  const blur = `${uid}-bokeh`
  const body = `${uid}-drop`
  return (
    <svg
      className={styles.layer}
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      preserveAspectRatio="xMidYMid slice"
    >
      <defs>
        <filter id={blur} x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="24" />
        </filter>
        {/* A bead on glass refracts the scene behind it: bright low in the bead,
            dark at its rim. */}
        <radialGradient id={body} cx="0.5" cy="0.62" r="0.6">
          <stop offset="0" stopColor="#f4f7fb" stopOpacity="0.9" />
          <stop offset="0.55" stopColor="#c9d3df" stopOpacity="0.55" />
          <stop offset="1" stopColor="#3b4656" stopOpacity="0.75" />
        </radialGradient>
      </defs>

      {/* Out-of-focus sky behind the glass. */}
      <g filter={`url(#${blur})`}>
        <ellipse cx="370" cy="30" rx="120" ry="70" fill="#2e5eb4" />
        <ellipse cx="70" cy="60" rx="80" ry="45" fill="#3d6cc0" />
        <ellipse cx="220" cy="150" rx="130" ry="80" fill="#eef2f7" />
        <ellipse cx="430" cy="220" rx="90" ry="60" fill="#e2e8ef" />
        <ellipse cx="80" cy="270" rx="110" ry="45" fill="#6f7b8a" />
        <ellipse cx="310" cy="300" rx="120" ry="40" fill="#828fa0" />
      </g>

      {trails.map((t, i) => (
        <path
          key={`t${i}`}
          d={t.d}
          fill="none"
          stroke="#ffffff"
          strokeOpacity="0.28"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
      ))}

      {[...drops, ...trails.map((t) => t.end)].map((d, i) => (
        <g key={i} transform={`translate(${d.x.toFixed(1)} ${d.y.toFixed(1)})`}>
          <ellipse
            cx={d.r * 0.12}
            cy={d.r * 0.22}
            rx={d.r}
            ry={d.r * d.e}
            fill="#1d2633"
            fillOpacity="0.45"
          />
          <ellipse rx={d.r} ry={d.r * d.e} fill={`url(#${body})`} />
          {d.r > 1.6 && (
            <circle cx={-d.r * 0.35} cy={-d.r * 0.42} r={d.r * 0.2} fill="#ffffff" />
          )}
        </g>
      ))}
    </svg>
  )
}
