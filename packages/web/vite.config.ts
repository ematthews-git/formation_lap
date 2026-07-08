import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Port is pinned to 5173 because that's the API's default local CORS origin
// (ALLOWED_ORIGINS in packages/api/src/formation_api/main.py). Deployed origins
// are configured via that env var, not here.
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
})
