# Seattle Councilmatic — frontend

The single-page React app for [seattlecouncilmatic.org](https://www.seattlecouncilmatic.org).
Vite-built, served by Django in prod and by `vite dev` (with HMR) in
local development.

## Stack

- **React 19** with React Router 7 for client-side routing
- **Vite 7** for dev server, HMR, and production bundling
- **Leaflet** + **react-leaflet** for the council district + zoning maps
- **lucide-react** for icons
- Plain `fetch()` for API calls — no SWR/React Query layer
- ESLint with the React Hooks + React Refresh plugins
- No CSS framework: per-component CSS files, classnames prefixed with
  the component (e.g. `.rep-detail-*` in `RepDetail.css`)

## Dev workflow

The recommended dev workflow runs Django and Vite side by side via
`docker compose up`. After containers are healthy:

- **<http://localhost:5173>** — Vite dev server with HMR. Use this for
  almost everything. Routes other than `/api/*`, `/admin/*`, `/cms/*`
  are served by Vite; the rest are proxied to Django on `:8000` (see
  `vite.config.js` for the middleware).
- **<http://localhost:8000>** — Django + the production-style SPA
  bundle. Useful only for verifying the prod build (`npm run build`
  output). Routine frontend work doesn't need this rebuilt.

The Vite middleware also rewrites bare `/admin` and `/cms` requests to
their slash variants — without that the SPA catch-all matches first
and shows a 404.

## Project conventions

- **One file per component**, paired with one CSS file: `Foo.jsx` +
  `Foo.css`. The CSS is scoped via classname prefixes, not modules.
- **No CSS-in-JS, no inline styles** beyond per-instance dynamic values
  (e.g. district color), which are passed as CSS custom properties on
  the element and consumed via `var()` in the stylesheet. See
  [AUDIT_FINDINGS.md](../AUDIT_FINDINGS.md) "Color" section for why.
- **Accessibility conventions are documented** in
  [AUDIT_FINDINGS.md](../AUDIT_FINDINGS.md) under "Conventions to keep
  applying" (labels, focus, contrast, headings, landmarks, live
  regions, document title, Leaflet maps). Apply them on any new UI.

## Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` | Start the Vite dev server on `:5173` |
| `npm run build` | Production build to `dist/` (consumed by Django in prod) |
| `npm run preview` | Serve the built bundle locally for spot-checks |
| `npm run lint` | ESLint over `src/` |

In Docker:

```bash
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```
