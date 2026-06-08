import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite dev server config.
//
// The Flask backend runs on http://localhost:5000. During dev we use
// Vite (port 5173) and proxy any /api, /simulate, /save, /load, /list-circuits
// requests through to Flask. This lets the React app `fetch('/api/ask', ...)`
// without any cross-origin pain.
//
// For production, run `npm run build` and have Flask serve the resulting
// `dist/` folder (or host it separately on Vercel/Netlify pointing at the
// Flask API URL).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api':            'http://localhost:5000',
      '/simulate':       'http://localhost:5000',
      '/save':           'http://localhost:5000',
      '/load':           'http://localhost:5000',
      '/list-circuits':  'http://localhost:5000',
    },
  },
})
