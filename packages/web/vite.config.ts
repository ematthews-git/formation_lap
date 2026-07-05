import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Port is pinned to 5173 because the API's CORS allowlist
// (packages/api/src/formation_api/main.py) only permits that origin.
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    allowedHosts: ["nimble-brook-privacy.ngrok-free.dev"],
  }
})
