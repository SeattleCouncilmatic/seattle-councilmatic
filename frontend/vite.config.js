import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
//
// `base` is conditional:
//   * Production build → `/static/` so the bundle's hashed asset URLs
//     match Django's STATIC_URL when the SPA is served by the
//     `react_app` view in prod.
//   * Dev server → `/` so `localhost:5173/reps/<slug>/` "just works".
//     Vite's history fallback serves index.html for unknown paths,
//     and React Router takes over from there.
//
// The `server.proxy` block forwards everything Django owns
// (`/api`, `/admin`, `/cms`, `/static`, `/media`) to the app
// container at port 8000. Note: Vite's own dev assets live at
// `/@vite/...` and `/src/...`, so they don't clash with `/static`.
// SPA routes (anything else) get the index.html fallback and
// React Router renders the correct page.
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/' : '/',
  plugins: [react()],
  server: {
    proxy: {
      '/api':    { target: 'http://app:8000', changeOrigin: true },
      '/admin':  { target: 'http://app:8000', changeOrigin: true },
      '/cms':    { target: 'http://app:8000', changeOrigin: true },
      '/static': { target: 'http://app:8000', changeOrigin: true },
      '/media':  { target: 'http://app:8000', changeOrigin: true },
    },
  },
}))
