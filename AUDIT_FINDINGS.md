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

## Known false positives — do not chase

These show up in some accessibility tools but represent tool limitations rather than real-world barriers. Real screen readers (NVDA, JAWS, VoiceOver, Orca) handle the underlying patterns correctly.

### FP.1 Firefox Inspector flags the React `#root` div as "clickable but not focusable"

Reported as: `Clickable elements must be focusable and should have interactive semantics` on `<div id="root">` with `actions: ["Click"]`.

**Why it fires:** React 17+ uses event delegation — it attaches a single `click` listener to the root container and dispatches synthetically to your components. Firefox's accessibility tree picks up that listener and reports the root as clickable. The listener is React plumbing, not a UI affordance.

**Why it's harmless:** Real screen readers don't announce `<div id="root">` as clickable. Keyboard users don't try to interact with it. Every React app has this finding; the React community treats it as expected.

### FP.2 Firefox Inspector flags `<input type="date">` spinbutton children as missing labels

Reported as: `Form elements should have a visible text label` on the spinbutton role inside a date input, even when the parent `<input type="date">` is correctly labeled via `<label htmlFor>`.

**Why it fires:** Firefox decomposes `<input type="date">` into the parent input + three child spinbuttons (month/day/year). Each spinbutton is its own accessible object. Firefox's name-derivation walk doesn't always propagate the parent's label down to the children, so each spinbutton appears to lack a name.

**Why it's harmless:** Other browsers (Chrome, Safari) don't decompose date inputs the same way; axe doesn't see the spinbutton children. Real screen readers announce the date input based on the labeled parent — they don't navigate into the spinbutton children individually as if they were unlabeled. The PR #114 explicit-`htmlFor`/`id` switch is the right pattern regardless; the FF Inspector finding persists as a known browser quirk.

**Workarounds we declined:** Re-adding redundant `aria-label` (might satisfy FF, would clutter the markup with redundancy). Replacing native `<input type="date">` with a custom date picker library (loses native UX for one Inspector check).

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

---

## Conventions to keep applying

The audit shipped 17 PRs (#105–#124) clearing the priority items above plus the runtime issues the FF Inspector + axe pass surfaced. Patterns established along the way — apply on any new UI to avoid re-introducing the same findings.

### Form fields

- **Visible label above each control.** `<label className="...-field"><span className="...-field-label">Search</span><input/></label>`. `aria-label` alone fails axe `label` and WCAG 2.5.3.
- **Date inputs need explicit `htmlFor`/`id`.** Firefox's Inspector doesn't reliably detect implicit `<label>`-wrapping for `<input type="date">`. Use `<div className="...-date-field"><label htmlFor="x" ...>From</label><input id="x" type="date"/></div>`.
- **Self-sufficient labels.** "to" alone fails — use "Date to" / "Introduced to".
- **Drop redundant `aria-label`** once a visible label exists; the visible label becomes the source of truth.

### Disabled state

Use **explicit colors**, not `opacity`. Opacity composites against the page bg and fails WCAG 1.4.3 even at 0.6. Pattern:

```css
.btn:disabled {
  color: #6b7280;
  border-color: #6b7280;
  background: #ffffff;
  cursor: not-allowed;
}
```

`#6b7280` on `#ffffff` ≈ 4.83:1 — clears AA, still reads as faded.

### Color

- **Text on white**: `#9ca3af` (gray-400, 2.85:1) fails AA. Use `#6b7280` (gray-500, 4.83:1) at minimum.
- **The Tab10 district palette is for fills only**, not text. D2 orange / D3 green / D4 red / D5 purple all fail AA on white. For text, use brand navy `#2E3D5B` (~9.5:1).
- **Decorative `aria-hidden` elements** (e.g. breadcrumb `/` separators) are exempt from contrast requirements — `#9ca3af` is fine there.
- **Per-instance dynamic colors** that interact with CSS shorthands: pass via CSS variable, consume with `var()` inside the CSS itself. Inline React `borderColor`/`borderLeftColor` longhand can lose to CSS shorthands unpredictably.

  ```jsx
  style={{ '--card-accent': accent }}
  ```

  ```css
  border-left: 4px solid var(--card-accent, #2E3D5B);
  ```

### Focus

- **Use `:focus-visible`, not `:focus`** — keyboard-only indicator, doesn't fire on every mouse click.
- **Card-wrappers need explicit `:focus-visible`** with a 2px navy outline + offset. Browser default isn't reliable across browsers.
- **Focus rings via box-shadow**: ≥ 0.4 alpha (~3:1) to clear WCAG 2.4.13. 0.15 fails.
- **State-driven highlight + CSS focus**: when an inline highlight covers focus visually, set `outline: 'none'` in the inline style to suppress the underlying CSS outline and avoid double rings.
- **Inputs that delegate focus to a parent's `:focus-within`** still need their own `:focus-visible` rule — Firefox checks per-element.

### Heading hierarchy

- **One `<h1>` per page.** Header brand mark is `<p className="title">`, not `<h1>` (Header renders on every page).
- **No level skips.** Index pages: h1 (page) → h2 (sections/filters) → h3 (cards). LegislationCard / EventCard titles are `<h3>`.
- Homepage h1 lives in LegislationHero.

### Landmarks

- **One `<main id="main-content" tabIndex={-1}>`** wrapping `<Routes>` in `App.jsx`. Per-page outer is `<div className="...-page">`, not `<main>`.
- **Skip-link** `<a href="#main-content" className="skip-link">` is the first focusable element on every page (rendered in `App.jsx` before `<Header>`).
- **Per-page**: one `<header>`, optional `<aside>`, `<nav aria-label="Breadcrumb">`, `<nav aria-label="Pagination">`.

### Live regions

| State | Role | Why |
| --- | --- | --- |
| Loading | `role="status"` | Polite — announces when SR user is idle |
| Standalone error | `role="alert"` | Assertive — interrupts |
| Combined summary (Loading → Results → Error) | `role="status"` | Don't aggressively interrupt on filter changes |

### Document title

Per-page `<title>` via `useDocumentTitle(pageTitle)` from `frontend/src/hooks/useDocumentTitle.js`. Static pages pass a literal string; detail pages pass `data?.field` — hook handles `null`/`undefined` by falling back to the bare site name so the previous page's title doesn't leak during loading.

### Maps (Leaflet)

- Pass `attributionControl: false` to `L.map()` — the built-in attribution trips Firefox's "clickable but not focusable" check.
- Render OSM/CARTO attribution as a plain `<p>` with `<a>` tags below the map (license-compliant and natively focusable). Pattern in `CouncilMap.jsx` and `DistrictMiniMap.jsx`.
- Map div needs an accessible name. Interactive maps (CouncilMap): `role="application"` + descriptive `aria-label`. Static maps (DistrictMiniMap): `role="img"` + `aria-label="Boundary of District N"`.
- For half-step zoom levels (smoother +/- and tighter `fitBounds`): set `zoomSnap: 0.5`.

### Reduced motion + utilities

- Global `@media (prefers-reduced-motion: reduce)` rule in `index.css` collapses all transitions/animations. Don't add new persistent animations without checking.
- `.sr-only` utility class lives in `index.css` for visually-hidden labels and skip-link text.

### Vite scaffold defaults are dangerous

`frontend/src/index.css` should be minimal — only typography, body reset, the `.sr-only` utility, and the reduced-motion rule. Don't reintroduce Vite's default `<a>` / `<button>` / `<h1>` styles, and never the `prefers-color-scheme: light` block that sets dark `#1a1a1a` bg (the original scaffold had this backwards).

### Text-link underlines

Text-style links (breadcrumbs, sponsor names, doc names, RCW/SMC refs, external links) use `text-decoration: underline` persistently. Card-wrappers and button-styled links keep `text-decoration: none` — their chrome already signals interactivity.
