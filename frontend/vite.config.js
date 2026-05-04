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
    proxy: {
      '/api':    { target: 'http://app:8000', changeOrigin: true },
      '/admin':  { target: 'http://app:8000', changeOrigin: true },
      '/cms':    { target: 'http://app:8000', changeOrigin: true },
      '/static': { target: 'http://app:8000', changeOrigin: true },
      '/media':  { target: 'http://app:8000', changeOrigin: true },
    },
  },
}))
