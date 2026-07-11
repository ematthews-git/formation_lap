import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
// Self-hosted fonts (replaces the Google Fonts CDN): only the weights the
// stylesheets actually use — sans/mono 400–600, display 500–700.
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/ibm-plex-mono/600.css'
import '@fontsource/saira-condensed/500.css'
import '@fontsource/saira-condensed/600.css'
import '@fontsource/saira-condensed/700.css'
import './styles/global.css'
import App from './App.tsx'
import { SectionBoundary } from './components/common/SectionBoundary.tsx'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Briefing data changes slowly; avoid refetch churn while developing.
      staleTime: 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* Last-resort boundary for errors outside the per-section ones (header,
          top bar) — degrades to an error card instead of a white screen. */}
      <SectionBoundary label="FORMATION_LAP // BRIEFING">
        <App />
      </SectionBoundary>
    </QueryClientProvider>
  </StrictMode>,
)
