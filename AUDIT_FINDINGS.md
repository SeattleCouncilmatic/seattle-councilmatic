# Accessibility Audit — Static Pass

Captured 2026-05-01 by reading the SPA source under `frontend/src/`.
Findings are categorized by priority and grouped so multiple related
items can land in a single PR. Cross-checks against Firefox Dev
Edition's Accessibility Inspector + axe DevTools should follow.

WCAG references are AA unless noted.

---

## Priority 1 — definite fails

### P1.1 Vite scaffold defaults are actively wrong
[`frontend/src/index.css`](frontend/src/index.css) is the Vite starter file, mostly ignored by component CSS but still in effect at the root:

- [index.css:55-58](frontend/src/index.css#L55-L58) sets `:root { background-color: #1a1a1a }` *inside* the `prefers-color-scheme: light` media query — i.e., dark background when the user prefers light. Inverse of what it should be. Currently masked by `body { background: #f9fafb }` (set somewhere downstream) but shows during initial paint flashes and breaks if any descendant uses `background: inherit`.
- [index.css:16-23](frontend/src/index.css#L16-L23) sets default `<a>` color to `#646cff` (Vite purple). Most components override per-link, but any unstyled anchor inherits purple, which clashes with the navy `#2E3D5B` brand color and can fail contrast on tinted backgrounds (e.g. indigo summary cards).
- [index.css:36-49](frontend/src/index.css#L36-L49) sets default `<button>` background `#1a1a1a` and a `#646cff` hover border. Component buttons override, but any unstyled `<button>` (e.g. internal toggles) inherits the dark scaffold style.

**Fix:** strip `index.css` down to whatever the project actually needs (font-family, base typography, body bg). The scaffold defaults shouldn't be silently shaping unstyled elements.

### P1.2 No skip-link
WCAG 2.4.1 (Bypass Blocks) — keyboard users can't bypass the header/nav to reach main content. Repeating the nav on every page hits this hard.

[App.jsx](frontend/src/App.jsx) renders `<Header /> <Routes/> <Footer />`. Add a visually-hidden `<a href="#main-content">Skip to main content</a>` as the first focusable element in `<Header>` (or in App.jsx before Header), styled to become visible on focus. Each page component already wraps its content in `<main>` — add `id="main-content"` to those, or add a single `<main id="main-content">` wrapper around `<Routes>` and remove the per-page `<main>`.

### P1.3 HomePage has no `<main>` landmark
[App.jsx:23-30](frontend/src/App.jsx#L23-L30) — `HomePage` is a fragment containing `<LegislationHero>` + `<ThisWeek>`. Neither component renders `<main>`, so the homepage has no `<main>` landmark at all. Every other page has its own `<main>`. This breaks the skip-link target, screen reader landmark navigation, and "skip to main content" extension behavior.

**Fix coupling:** ties to P1.2. A single `<main id="main-content">` in App.jsx around `<Routes>` is the cleanest fix — covers the home page and replaces the per-page `<main>` (which currently produce 12+ `<main>` elements scattered across components).

### P1.4 Multiple `<h1>` elements per page
[Header.jsx:21](frontend/src/components/Header.jsx#L21) renders `<h1 className="title">Seattle Councilmatic</h1>` on every page. Each page also has its own `<h1>` (page subject). So every page has 2× `<h1>`.

Per WCAG 1.3.1 (Info and Relationships) and screen reader convention, the `<h1>` should identify the page's main subject. The site title belongs in a smaller heading or none at all (the `<header>` landmark already announces it).

**Fix:** change Header's `.title` from `<h1>` to `<p>` (or a `<span>`). The page heading hierarchy then reads cleanly: page `<h1>` → section `<h2>`s.

### P1.5 Heading levels skip
- [ThisWeek.jsx:10](frontend/src/components/ThisWeek.jsx#L10) uses `<h3>` for "tw-section-title" — but on the homepage, after fixing P1.4, the only h1 is in `LegislationHero` (which uses `<h2>`!). So homepage hierarchy currently reads h1 (Header) → h2 (Hero) → h3 (ThisWeek). After fixing P1.4, no h1 at all. ThisWeek should be `<h2>` and LegislationHero's section heading needs review.
- [LegislationCard.jsx:61](frontend/src/components/LegislationCard.jsx#L61) and [EventCard.jsx:84](frontend/src/components/EventCard.jsx#L84) use `<h4>` — on index pages where the page `<h1>` and section `<h2>` precede them, `<h3>` would be the right level (no skip). Currently h1 → h2 → h4 skips h3.

**Fix:** standardize index pages on h1 (page) → h2 (section/filters block) → h3 (card title).

### P1.6 Color contrast: `#9ca3af` on white fails AA
`#9ca3af` (Tailwind gray-400) on `#ffffff` is **2.85:1** — fails WCAG AA for normal text (needs 4.5:1) and large text (needs 3:1). Used as foreground text in:

- Breadcrumb separators ([About.css:23](frontend/src/components/About.css#L23), [LegislationDetail.css:35](frontend/src/components/LegislationDetail.css#L35), and similar across all breadcrumb files)
- "Last updated" / placeholder gray text in [EventCard.css:90](frontend/src/components/EventCard.css#L90), [EventDetail.css:32](frontend/src/components/EventDetail.css#L32), [LegislationDetail.css:391](frontend/src/components/LegislationDetail.css#L391), [LegislationHero.css:96](frontend/src/components/LegislationHero.css#L96)
- Cosponsor labels, breadcrumb-current text in many places

Some of these are decorative (breadcrumb `/` separators with `aria-hidden`) and could stay if confirmed decorative. The rest need to bump to `#6b7280` (gray-500, ~4.83:1, passes AA) at minimum.

`#6b7280` is widely used and passes AA for normal text. Audit the `#9ca3af` instances: keep only on `aria-hidden` decorative elements; everywhere else swap to `#6b7280`.

---

## Priority 2 — review needed

### P2.1 Focus indicator visibility
The pattern `outline: none; border-color: #2E3D5B; box-shadow: 0 0 0 3px rgba(46, 61, 91, 0.15);` is used for input/select focus across the app ([EventsIndex.css:75-79](frontend/src/components/EventsIndex.css#L75-L79) and similar). The 15% opacity on the box-shadow ring may not meet WCAG 2.2 SC 2.4.13 (Focus Appearance, AAA) which requires ~3:1 contrast against adjacent colors. Bumping the ring opacity to ~30-40% or using a solid 2px ring would be safer.

### P2.2 Card-wrapper links lack explicit focus styles
`.leg-card-link` ([LegislationCard.css:73-80](frontend/src/components/LegislationCard.css#L73-L80)), `.evt-card-link`, `.smc-detail-link`, etc. set `text-decoration: none; color: inherit` but no `:focus-visible` rule. They fall back to the browser default outline, which is OK on Chrome/Firefox but inconsistent. A consistent `:focus-visible { outline: 2px solid #2E3D5B; outline-offset: 2px; border-radius: ... }` rule across card wrappers would standardize keyboard affordance.

### P2.3 Icon button: hamburger toggle focus
The NavBar hamburger toggle ([NavBar.jsx:39-48](frontend/src/components/NavBar.jsx#L39-L48)) has `aria-expanded` and `aria-controls` correctly. When the menu opens, focus stays on the toggle — that's acceptable, but no focus is moved into the menu, and there's no focus trap. On mobile, tab order will continue past the menu into page content. Verify in browser whether this is a real issue.

### P2.4 No `aria-live` for dynamic content
Index pages filter the result list as users type/select. Screen readers don't get notified of result count changes. WCAG 4.1.3 (Status Messages) — add `aria-live="polite"` to a results-count element on `LegislationIndex`, `EventsIndex`, `MuniCodeIndex`, `Search`. Subtle but high-leverage for keyboard+SR users.

### P2.5 Loading and error states
"Loading…" text in [LegislationDetail.jsx:106](frontend/src/components/LegislationDetail.jsx#L106), [RepDetail.jsx:32](frontend/src/components/RepDetail.jsx#L32), and several others isn't in an aria-live region. SR users get no announcement of state changes between loading and loaded.

**Fix:** wrap loading/error messages in an `<div role="status" aria-live="polite">` or use `<output>`.

### P2.6 Reduced motion not honored
No `@media (prefers-reduced-motion: reduce)` rules anywhere. The transitions are short (0.15s on hover/focus), but `transition: opacity 0.15s` on `.evt-doc-btn:hover`, plus the homepage skyline cross-fade (if any), should respect the user's preference.

**Cheap fix:** add a global rule in `index.css`:
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

### P2.7 Per-page document `<title>`
Every page currently has `<title>Seattle Councilmatic</title>` from the static SPA shell. WCAG 2.4.2 (Page Titled) is satisfied minimally, but a page-aware title (e.g., `CB 121200 — Seattle Councilmatic` on a bill detail) makes a much better screen-reader experience and improves browser history / tab labeling.

**Implementation:** small `useDocumentTitle(title)` hook plumbed into ~8 detail components; falls back to the static title on index pages.

---

## Priority 3 — minor / nice-to-have

### P3.1 `.sr-only` defined inside one component file
[LegislationHero.css:46](frontend/src/components/LegislationHero.css#L46) defines `.sr-only` for visually-hidden labels. The class is global because CSS isn't scoped, but the placement is misleading — it implies the class is hero-specific. Move to a global utility CSS (or `index.css` after the scaffold-defaults cleanup).

### P3.2 Duplicate routes for trailing slash
[App.jsx](frontend/src/App.jsx) registers each path twice (with and without trailing slash, e.g. `/legislation` and `/legislation/`). Not an a11y issue per se, but it's noise and could confuse SR users if they trigger different behaviors. React Router supports this idiomatically via `*` matching or a single canonical path. Defer.

### P3.3 Footer / About linked redundantly
Both `<Header>`'s NavBar and `<Footer>` link to About. SR users tabbing through the page get the same destination twice. Not strictly wrong but worth knowing.

---

## Items confirmed OK

- `<html lang="en">` is set in [index.html](frontend/index.html). ✓
- Form inputs and selects all have either `<label>` or `aria-label`. ✓
- Icon-only buttons (search clear, hamburger) have `aria-label`. ✓
- Decorative icons (search glyphs, breadcrumb chevrons) use `aria-hidden="true"`. ✓
- `aria-current="page"` on the active nav item. ✓
- `aria-expanded` / `aria-controls` on the hamburger toggle. ✓
- `aria-pressed` on toggle button group ([EventsIndex.jsx:181](frontend/src/components/EventsIndex.jsx#L181)). ✓
- `role="search"` on search forms. ✓
- `role="alert"` on error / status messages. ✓
- No `onClick` on `<div>` / `<span>` (proper button/anchor usage). ✓
- All `:focus` rules that drop `outline: none` provide a replacement via border-color + box-shadow ring (visible — see P2.1 for ring contrast nuance). ✓
- All `<input>` / `<select>` have associated labels (visual or sr-only). ✓
- Persistent underlines on text links (shipped in PR #94) — affordance baseline is solid. ✓
- Per-page `<main>`, `<header>`, `<nav>`, `<aside>` landmarks on every detail page. ✓
- Pagination controls use `<nav aria-label="Pagination">`. ✓

---

## Suggested PR breakdown

1. **a11y/scaffold-cleanup** *(quick, one PR)* — strip Vite scaffold defaults from `index.css` (P1.1), add reduced-motion rule (P2.6), move `.sr-only` to global (P3.1).
2. **a11y/skip-link-and-main** *(small)* — add skip-link, hoist `<main>` to App.jsx, add `id="main-content"` (P1.2 + P1.3).
3. **a11y/heading-hierarchy** *(small-medium)* — Header `<h1>` → `<p>`, ThisWeek `<h3>` → `<h2>`, card titles `<h4>` → `<h3>` (P1.4 + P1.5). Touches every index/card component but each change is mechanical.
4. **a11y/contrast-fixes** *(quick-medium)* — swap `#9ca3af` → `#6b7280` everywhere except `aria-hidden` decorative elements (P1.6). Touches ~12 CSS files.
5. **a11y/aria-live-and-loading** *(medium)* — add aria-live for index result counts and loading states (P2.4 + P2.5).
6. **a11y/per-page-title** *(medium)* — `useDocumentTitle` hook plumbed into detail components (P2.7).
7. **a11y/focus-visible** *(small)* — add explicit `:focus-visible` to card wrappers + bump focus ring opacity (P2.1 + P2.2).

After P1 items land, run Firefox Accessibility Inspector + axe DevTools on the flagship pages (Home, /legislation, a bill detail, /municode, an SMC section, /reps, a rep detail) to catch the runtime-only issues this static pass can't see (computed contrast, focus order, dynamic ARIA).
