import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API base URL comes from the environment at build time
// (docker-compose sets VITE_API_URL); defaults to local Django dev server.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
})
