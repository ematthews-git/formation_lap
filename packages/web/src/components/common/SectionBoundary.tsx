import { Component, type ReactNode } from 'react'
import { Panel } from './Panel'
import { PanelHeader } from './PanelHeader'
import { ErrorState } from './Status'

interface Props {
  /** Panel-header label for the fallback card, e.g. "STRATEGY_ENGINE". */
  label: string
  children: ReactNode
}

interface State {
  failed: boolean
}

/**
 * Per-section error boundary: a render error inside one briefing panel
 * degrades that panel to an ErrorState card instead of white-screening the
 * whole page. The riskiest inputs are the loosely-typed JSONB stats blobs
 * (sim_race_stats / circuit race-stats), which are poked via unknown-casts.
 */
export class SectionBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error(`[${this.props.label}] section failed to render:`, error)
  }

  render() {
    if (this.state.failed) {
      return (
        <Panel>
          <PanelHeader label={this.props.label} />
          <ErrorState message="this section hit an unexpected error and couldn't render" />
        </Panel>
      )
    }
    return this.props.children
  }
}
