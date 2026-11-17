/*
 * Liquid-glass maps, after kube.io's "Liquid Glass in the Browser: Refraction
 * with CSS and SVG" (https://kube.io/blog/liquid-glass-css-svg).
 *
 * The panel is modelled as a slab of glass (n = 1.5) whose edge rounds off in a
 * convex squircle bezel. For every pixel inside that bezel we work out how far
 * a straight-down ray is bent by the curved surface (Snell's law) and store the
 * shift in a displacement map: red = x, green = y, 128 = no shift. An SVG
 * <feDisplacementMap> then moves the backdrop pixels by that much, which is
 * what bends the photo at the rim. A second image holds the specular rim:
 * light from the upper left catching the bezel, brightest where the surface
 * faces the light.
 *
 * The maps are applied with a plain CSS `filter: url(#…)` on a copy of the
 * scene placed inside the panel (see components/common/LiquidGlass), not as a
 * `backdrop-filter`: SVG backdrop filters only render in Chromium, while SVG
 * filters on an element work in every engine.
 */

const N_GLASS = 1.5

/** Convex squircle height profile, t = 0 at the outer edge → 1 where the flat top starts. */
const surface = (t: number) => Math.pow(1 - Math.pow(1 - t, 4), 0.25)

/** Relative refraction shift across the bezel, sampled once and normalised to 0..1. */
const SAMPLES = 128
const PROFILE: number[] = (() => {
  const out: number[] = []
  const d = 0.001
  for (let i = 0; i < SAMPLES; i++) {
    const t = Math.min(1 - d, Math.max(d, i / (SAMPLES - 1)))
    const slope = (surface(t + d) - surface(t - d)) / (2 * d)
    const incidence = Math.atan(slope)
    const refracted = Math.asin(Math.sin(incidence) / N_GLASS)
    out.push(Math.tan(incidence - refracted))
  }
  const max = Math.max(...out)
  return out.map((v) => v / max)
})()

export interface LiquidGlassMaps {
  displacement: string
  specular: string
}

export interface LiquidGlassShape {
  width: number
  height: number
  /** Corner radius of the panel, px. */
  radius: number
  /** Width of the curved rim that refracts, px. */
  bezel: number
}

/** Render both maps for a rounded rectangle; returns PNG data URLs. */
export function buildLiquidGlassMaps({ width: w, height: h, radius, bezel }: LiquidGlassShape): LiquidGlassMaps | null {
  if (w < 2 || h < 2) return null
  const r = Math.min(radius, w / 2, h / 2)
  const disp = document.createElement('canvas')
  const spec = document.createElement('canvas')
  disp.width = spec.width = w
  disp.height = spec.height = h
  const dctx = disp.getContext('2d')
  const sctx = spec.getContext('2d')
  if (!dctx || !sctx) return null
  const dimg = dctx.createImageData(w, h)
  const simg = sctx.createImageData(w, h)
  const dd = dimg.data
  const sd = simg.data

  // Light from the upper left (unit vector pointing toward the light).
  const lx = -0.5
  const ly = -0.866
  const rimBand = bezel * 0.4
  const hw = w / 2
  const hh = h / 2

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4
      dd[i] = 128
      dd[i + 1] = 128
      dd[i + 2] = 128
      dd[i + 3] = 255

      const px = x + 0.5 - hw
      const py = y + 0.5 - hh
      const qx = Math.abs(px) - (hw - r)
      const qy = Math.abs(py) - (hh - r)
      // Signed distance to the rounded rectangle (negative inside).
      const sdf =
        Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r
      const dist = -sdf
      if (dist < 0 || dist >= bezel) continue

      // Outward surface normal in the plane.
      let nx: number
      let ny: number
      if (qx > 0 && qy > 0) {
        const len = Math.hypot(qx, qy) || 1
        nx = qx / len
        ny = qy / len
      } else if (qx > qy) {
        nx = 1
        ny = 0
      } else {
        nx = 0
        ny = 1
      }
      nx *= Math.sign(px) || 1
      ny *= Math.sign(py) || 1

      // Refraction: the edge samples from further in, magnifying the rim.
      const t = dist / bezel
      const m = PROFILE[Math.min(SAMPLES - 1, Math.round(t * (SAMPLES - 1)))]
      dd[i] = Math.round(128 - nx * m * 127)
      dd[i + 1] = Math.round(128 - ny * m * 127)

      // Specular rim: key light on the upper-left edges, a weaker bounce opposite.
      if (dist < rimBand) {
        const e = Math.pow(1 - dist / rimBand, 1.6)
        const facing = nx * lx + ny * ly
        const key = Math.max(0, facing)
        const bounce = Math.max(0, -facing) * 0.45
        const a = Math.min(1, (Math.pow(key, 1.5) + bounce + 0.12) * e)
        sd[i] = 255
        sd[i + 1] = 255
        sd[i + 2] = 255
        sd[i + 3] = Math.round(a * 235)
      }
    }
  }

  dctx.putImageData(dimg, 0, 0)
  sctx.putImageData(simg, 0, 0)
  return { displacement: disp.toDataURL('image/png'), specular: spec.toDataURL('image/png') }
}
