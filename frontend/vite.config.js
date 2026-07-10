import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite's SPA history-fallback middleware intercepts extensionless
// paths and serves index.html before the proxy runs, so a bare
// `/admin` or `/cms` (no trailing slash) ends up on the SPA's
// NotFound instead of getting proxied to Django. Django itself
// would APPEND_SLASH-redirect these to the slash form; we do the
// same here, ahead of every other middleware, so the proxy then
// matches the slash variant and forwards to Django cleanly.
const djangoTrailingSlashRedirect = {
  name: 'django-bare-route-trailing-slash',
  configureServer(server) {
    const bare = new Set(['/admin', '/cms'])
    server.middlewares.use((req, res, next) => {
      // Strip any querystring before the comparison so `/admin?foo=bar`
      // also redirects to `/admin/?foo=bar` cleanly.
      const [path, query] = (req.url || '').split('?')
      if (bare.has(path)) {
        res.writeHead(302, {
          Location: path + '/' + (query ? '?' + query : ''),
        })
        res.end()
        return
      }
      next()
    })
  },
}

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
//
// Plain string-prefix proxy keys. The bare `/admin` / `/cms` cases
// are handled separately by the `djangoTrailingSlashRedirect` plugin
// above (regex keys don't help because Vite's SPA fallback runs
// before the proxy for extensionless paths).
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/' : '/',
  plugins: [djangoTrailingSlashRedirect, react()],
  server: {
    // Poll the filesystem for changes instead of relying on inotify.
    // The dev server runs in a Docker container with the source bind-
    // mounted from a Windows host, and inotify events don't cross that
    // boundary — so without polling, Vite never sees edits or `git pull`s
    // and HMR silently stops firing (you'd see stale modules until a
    // container restart). Polling has a small CPU cost but is the
    // standard fix for Docker-on-Windows dev.
    watch: { usePolling: true },
    proxy: {
      // /api/digests keeps the browser's Host header (changeOrigin: false):
      // the subscribe endpoint builds the verification-email confirm link
      // with build_absolute_uri, so under changeOrigin the emailed link
      // would point at the Docker-internal `app:8000` instead of
      // localhost:5173. Must stay ABOVE the general /api key — Vite uses
      // the first matching prefix.
      '/api/digests': { target: 'http://app:8000', changeOrigin: false },
      '/api':    { target: 'http://app:8000', changeOrigin: true },
      '/admin':  { target: 'http://app:8000', changeOrigin: true },
      '/cms':    { target: 'http://app:8000', changeOrigin: true },
      '/static': { target: 'http://app:8000', changeOrigin: true },
      '/media':  { target: 'http://app:8000', changeOrigin: true },
      // Django-owned digest token pages (email links land here). The
      // SPA-owned /digests/subscribe and /digests/preferences are NOT
      // proxied — they fall through to the history fallback + React Router.
      '/digests/confirm':     { target: 'http://app:8000', changeOrigin: false },
      '/digests/manage':      { target: 'http://app:8000', changeOrigin: false },
      '/digests/unsubscribe': { target: 'http://app:8000', changeOrigin: false },
    },
  },
}))
