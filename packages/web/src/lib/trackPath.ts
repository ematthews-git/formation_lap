/**
 * Fallback circuit outline (the original mockup blob), used when a circuit has
 * no generated `track_outline` yet (new venues without telemetry). Generated
 * outlines come from the backend in the same viewBox (0 0 400 248).
 */
export const FALLBACK_TRACK_PATH =
  'M58 196 C 80 150, 84 116, 122 116 C 146 116, 152 134, 174 136 C 214 140, 228 92, 262 90 C 308 88, 332 70, 346 90 C 358 108, 332 126, 296 132 C 264 137, 246 152, 260 172 C 274 192, 322 188, 332 208 C 339 223, 314 230, 284 226 C 240 220, 198 214, 176 207 C 138 195, 112 226, 86 216 C 64 207, 50 210, 58 196 Z'

/** First point of an SVG path (its leading `M x y`) — the start/finish line. */
export function pathStartPoint(d: string): [number, number] {
  const m = /M\s*(-?[\d.]+)[\s,]+(-?[\d.]+)/.exec(d)
  return m ? [parseFloat(m[1]), parseFloat(m[2])] : [0, 0]
}
