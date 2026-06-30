import { buildSparkline } from '../../lib/sparkline'

interface Props {
  /** Recent finishing positions, oldest → newest (1 = win). */
  form: number[]
  color: string
}

/** Thin last-N-results sparkline in an 84×26 box. */
export function Sparkline({ form, color }: Props) {
  const { points, lastX, lastY } = buildSparkline(form)
  return (
    <svg width="84" height="26" viewBox="0 0 84 26" style={{ overflow: 'visible' }}>
      <polyline
        points={points}
        fill="none"
        stroke="rgba(255,255,255,.5)"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={lastX} cy={lastY} r="2" fill={color} />
    </svg>
  )
}
