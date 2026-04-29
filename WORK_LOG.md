# Work Log

Long-lived context for Seattle Councilmatic that git and GitHub can't tell you:
locked decisions, known follow-up threads, and a chronological merge log.
**Branch state lives in `gh pr list` — this file does not track it.**

---

## Decisions

- **Frontend ownership.** Django admin at `/admin/` and Wagtail admin at `/cms/` stay server-rendered. The Vite React SPA owns `/` and every unmatched path; Django's `react_app` view returns `frontend/dist/index.html` for those. `STATIC_URL` is `/static/` and Vite's `base` matches.
- **`base.html` retained.** Kept (with webpack-loader stripped) because `404.html` and `500.html` extend it via `handler404`/`handler500`. Don't delete unless you also rewrite the error templates.

## Up next

Prioritized to-do. Quick wins flagged with *(quick)*.

**SPA index/search pages** (each likely its own PR; specifics TBD when we pick them up)
- **Index polish** (deferred from PRs #30 and #31). *Legislation:* classification filter (Bill/Resolution/etc.), sort controls, sponsor filter. *Events:* committee-name dropdown (separate from type), date-range filter. *Both:* NavBar's hash-anchor stubs (`#about`, `#how-it-works`, `#my-council-members`, `#glossary`) still point at homepage sections that don't exist yet — wire them up as those sections ship, or convert to real `/path` Links. NavBar isn't shown on the index pages (only on the homepage); think about whether the index pages should get their own header/nav. CSS class names `.meeting-card-*` / `.mtg-detail-*` weren't renamed when MeetingCard/MeetingDetail → EventCard/EventDetail in PR #31; rename if/when those files get more substantive changes.

**Frontend polish & site chrome**
- **Events: capture EventTime in pupa scraper** (deferred from the events-filter PR). Every event in the DB has `start_date` set to either `07:00:00+00:00` or `08:00:00+00:00` — exactly midnight Pacific (offset depending on DST). Legistar's API exposes `EventDate` and `EventTime` as separate fields, but the scraper only captures the date and stores it as midnight-local. Real meeting times (9:30 AM, 2:00 PM, etc.) aren't in our DB at all. Frontend currently hides the time portion to avoid showing "midnight" everywhere; restore the `hour` / `minute` / `timeZoneName` keys in `EventCard.formatEventDate` and `EventDetail.formatDateTime` once the scraper picks up `EventTime`. Re-scrape required after the fix.
- **NavBar mobile hamburger** (deferred from PR #33). NavBar currently wraps via `flex-wrap` on narrow screens; if usability becomes a problem, replace with a proper hamburger menu.

**LLM summaries — wire up the existing infrastructure**
- Models, service module, and prompts already exist (`seattle_app/models.py:47,84` for `MunicipalCodeSection.plain_summary` + `LegislationSummary`; `seattle_app/services/claude_service.py` for `summarize_section`/`summarize_legislation` with full prompts). Nothing runs them and nothing surfaces them to users yet.
- Three pieces to ship the feature end-to-end:
  1. **Management command** to batch-summarize sections and bills (e.g., `summarize_smc_sections`, `summarize_legislation`) — handle prompt caching, rate limits, resumability, and skip already-summarized rows.
  2. **API**: extend `/api/legislation/<slug>/` to include `llm_summary` (summary, impact_analysis, key_changes); add `/api/smc/<section>/` (or similar) for section summaries.
  3. **Frontend**: render summary in `LegislationDetail` (probably above the action history). Decide whether to surface SMC section summaries — depends on whether there's a user-facing SMC browser yet.
- Open design questions: which Claude model? per-section caching strategy? batch via Anthropic Batch API to halve cost?

**Parser quality** (post-fix re-parse 2026-04-26 after `93cb885`: 7,435 sections + 1 `TitleAppendix` / 28 `ParseValidationIssue` rows / 234 official + 1 synthesized subchapter / 8 declared-but-empty)
- **Last 1 missing section** (`23.48.235`). The PDF lacks a clean section heading: section number lives in the running header (`'SEATTLEMIXED 23.48.235'`) and the title `'Upper-Level Setbacks'` appears on its own line after a figure caption (`'Map A for 23.48.235'`). Probably PDF source data issue — defer unless we find a generalizable fix. (`23.50A.160`, `23.76.067`, `25.24.030` all recovered this session — see Done. `12A.14.160` confirmed nonexistent: not in PDF, TOC jumps from `.150` to `.175`, no `ParseValidationIssue` row for it, dropped from the missing list. `5.48.050` recovered via PR #28's `Ord. + §` boundary rule.)
- **Column-split title-fold returns wrong wrap continuation.** Visible on `8.38.010 Short title "Canna-` where the soft-hyphen fold-during-emit (`if title.endswith("-"): title += next_line`) takes the literal next line in reading order, but pdfplumber's column-aware reader puts the wrong column's wrap there. Result: title becomes `Short title "CannaThis Chapter 8.38 shall constitute the` instead of `Short title "Cannabis Employee Job Retention Ordinance"`. Probably needs lookahead through the line list to find the actual wrap (look for the line that, prepended to the hyphen-broken title, reads grammatically) — or skip column-split title folds entirely and accept the truncated title.
- **Table-aware extraction for table-heavy LUC sections.** Sections like `23.47A.004` and `23.54.015` contain large permission tables (Table A "Permitted and prohibited uses by zone"). pdfplumber's column-aware word extraction loses table structure: the cell values arrive as a bag of bare codes (`X X X CCU CCU`, `P P P P P`, etc.) with no row labels (use names) attached, so it's impossible to tell "is a restaurant permitted in NC2?" from the parsed text. Use `pdfplumber.extract_tables()` to detect and serialize tables (probably as markdown rows) and substitute them in place where the column-aware reader currently emits jumbled cells. Applies to `23.47A.004`, `23.54.015`, and likely most LUC sections that reference "Table A for X.Y.Z".
- **Mixed-line TOC entries with embedded subchapter dividers** — chapters like 25.10 have TOC lines like `25.10.110 Applicability. Subchapter II. Definitions` where a section number AND a subchapter divider share one line. SECTION_RE matches first and the subchapter divider is lost as part of the section title, so Subchapter II is missed from the TOC scan. Would need to split such lines on the embedded `Subchapter X` token before regex matching, or run a second pass that detects `Subchapter X` substrings inside section titles.

## Open threads

Lower-priority backlog — fix when you're already in the area, not worth scheduling. (Empty for now; promote items here from Up next when they're deferred.)

---

## Conventions

**Branch names:** `<area>/<short-desc>` — e.g. `parser/subchapter-toc`, `frontend/vite-cutover`, `backfill/landmark-types`.

**Before switching branches:** WIP commit (`wip: <short-state>`) and push so nothing is orphaned in a detached working tree.

**Branch follow-ups from `main`, not from in-flight branches.** Stack only when the new work genuinely depends on the prior branch's code. Stacking on an unmerged branch costs a rebase later — root cause of the WORK_LOG conflict on `frontend/spa-notfound`.

**Include the Done-move in the same PR that ships the work.** Add the workstream's entry under `## Done` in the same commit. Avoids the "stale section after merge" tax we kept hitting.

**Pre-flight at session start:** `git fetch && git log main..origin/main` to catch divergence between local and remote `main` before doing anything else. We lost time to a 16-commit divergence in 2026-04 that this would have caught in one command.

---

## Done

### Legislation — date-range filter — committed 2026-04-28
Third of the index-polish bundle. `/legislation/` gets two date inputs ("Introduced from … to …") that filter on the bill's earliest action date. Both bounds inclusive; either can be set independently.

API: new `introduced_after` and `introduced_before` query params, validated against `^\d{4}-\d{2}-\d{2}$`. Malformed values silently ignored (matches the defensive pattern used elsewhere). The filter runs on a `Min('actions__date')` annotation applied conditionally — only when at least one bound is set, so unfiltered queries skip the extra GROUP BY.

Subtle bit: OCD stores `BillAction.date` as a full ISO 8601 string with time + timezone (`'2026-04-07T14:00:00+00:00'`), not a bare date. Lexicographic `>=` comparison against a `'YYYY-MM-DD'` lower bound works as-is (any same-day timestamp string-sorts after the bare date), but `<=` against a bare-date upper bound would EXCLUDE same-day rows because the timestamp is longer than the bound. Fix: pad the upper bound with `'T99:99:99'` so any real time-of-day on that date sorts under it. Verified the boundary inclusivity: a single-day window `2026-03-04 → 2026-03-04` returns 5 bills introduced exactly on that date.

Frontend: parallel state for the two URL params, a new "Introduced from / to" row beneath the search/status row, two `<input type="date">` controls. Native browser date pickers → no extra dependencies.

### Municode — scoped search at title and chapter levels — committed 2026-04-28
Closes the last municode follow-up. The `/api/smc/?title=<n>` and `?chapter=<n>` filters have been wired since PR #36 but weren't surfaced anywhere in the UI; now both the title and chapter detail pages expose scoped search via an input below their header, and the index page renders a `Filtered to Title <n>` or `Filtered to Chapter <n>` pill when either filter is active.

**Title page** (`MuniCodeTitle.jsx`) — search input below the title header. Submitting navigates to `/municode?q=<term>&title=<title_number>`.

**Chapter page** (`MuniCodeChapter.jsx`) — search input below the chapter header. Submitting navigates to `/municode?q=<term>&chapter=<full-chapter-number>`.

Both share the same `.smc-scoped-search-*` styles (renamed from `.smc-chapter-search-*` after the title use case landed). Search button is disabled until the user types something.

**Index page** (`MuniCodeIndex.jsx`):
- Reads both `title` and `chapter` URL params, passes through to `/api/smc/`, re-fetches when either changes.
- Renders a `Filtered to …` pill above the results list with an X button. When both filters are present (rare — typically chapter alone since chapter implies title), the chapter pill takes precedence.
- Clearing the search input drops `q`, `title`, AND `chapter` — leaving search mode should clear all search-related state, not strand a scope pill in browse mode.

Verified the filter cascade: `q=parking` returns 878 sections code-wide; scoped to `title=23` (Land Use Code) returns 336; scoped to `chapter=23.47A` returns 15.

### Municode — FTS search snippets via `ts_headline` — committed 2026-04-28
Closes the "search snippets" Municode follow-up filed during PR #36. SMC FTS results now ship with a highlighted excerpt drawn from `full_text` so users can see the term-in-context without clicking through. Citation-mode results (e.g. `q=23.47A`) continue without a snippet — there's no body context to surface and the citation is already self-explanatory.

**Backend** — `smc_search`'s FTS path annotates the queryset with `SearchHeadline('full_text', query, start_sel='<mark>', stop_sel='</mark>', max_words=30, min_words=15, short_word=3)`. Cost is bounded: the annotation runs after `LIMIT`, so `ts_headline` only executes on the post-pagination slice (≤ 100 rows). Browse-mode and citation-mode skip the annotation entirely.

XSS defense via `_safe_snippet`: HTML-escape the entire raw snippet, then restore the `&lt;mark&gt;` / `&lt;/mark&gt;` sentinels we asked Postgres to insert. Anything tag-shaped in the source SMC text renders as text on the frontend; only `<mark>` survives. Frontend uses `dangerouslySetInnerHTML` knowing the input is sanitized.

`_safe_snippet` also collapses the parser's hard line breaks (`' '.join(snippet.split())`) so the excerpt reads as flowing prose rather than mid-sentence wraps from the PDF column layout.

**Frontend** — both consumers (`MuniCodeIndex` `/municode/?q=` and `Search` `/search?q=`) render `r.snippet` below the section title when present. CSS grid rows extended in `MuniCodeIndex.css` (`.smc-result-num` now spans `1 / -1` so the citation stays vertically centered alongside title/sub/snippet) and `Search.css` (new `grid-template-areas` for the row → snippet layout). `<mark>` styled with `#fef3c7` background, slight padding, semibold — not hidden but not loud.

Verified: `q=parking` returns "Conditional uses" with snippet `Park-and-pool lots in IG1 and IG2 zones in the Duwamish Manufacturing/Industrial Center, and park…` (English-stemmed match on `park`). `q=23.47A` (citation mode) returns `snippet: null` for every row — the bypass works.

### Frontend — `/about` page — committed 2026-04-28
Drafted with the user across one round; content land:
- Lead paragraph + "why this exists" paragraph framing the site as a re-presentation of the City's public records.
- "What's on the site" feature list with internal links into every surface (`/legislation`, `/events`, `/reps`, `/municode`, `/search`, `/`).
- Data sources broken out: bills/events from Legistar, council members from seattle.gov + Open Data Portal, SMC from the official PDF.
- Credits to DataMade (django-councilmatic upstream, MIT-licensed), the City of Seattle (data), and CARTO (basemap tiles).
- Source-code link to the GitHub repo + contact email (`jimmie@jimmiewifi.com` for now; user plans to set up a councilmatic.org address once registered).

NavBar's `About` flipped from a `#about` hash anchor stub (which had nowhere to go since the homepage doesn't have an `#about` section) to a real `Link to="/about"`. Routes added: `/about` and `/about/`.

Tone deliberately balanced civic-formal with community-project warmth per the user's preference. Forward-looking content (LLM summaries, pgvector retrieval, etc.) intentionally omitted — the page describes what works today; expand when new features ship.

### Reps — fix at-large contact-detail lookup hitting former holders — committed 2026-04-28
Closes the data quirk filed during PR #39. `_rep_row_to_dict` was fetching contact rows via `OCDPerson.objects.filter(memberships__label=label).first()`, which matches anyone who has *ever* held that membership label. For Position 9 both Sara Nelson (former) and Dionne Foster (current) match, and `.first()` returned Sara — so Dionne's email rendered as `sara.nelson@seattle.gov` everywhere her card appeared (the rep grid on `/reps/`, her own detail page, and the at-large block on the district pages).

Fix: thread `p.id` through `_query_current_council_members` and `_rep_row_to_dict` so the contact-detail lookup filters by Person primary key (always unique) instead of membership label. The query already JOINed on `opencivicdata_person`, so adding `p.id` to the SELECT is free; updated the four call sites (`list_districts_with_reps`, `list_at_large_reps`, `get_rep_by_slug`, `get_district_with_reps`) to pass it through. `get_district_with_reps`'s splat call (`_rep_row_to_dict(*rows[0])`) absorbs the new tuple shape with no change.

Verified end-to-end: `/api/reps/`, `/api/reps/dionne-foster/`, and `/api/reps/districts/7/` all now return Dionne's `dionne.foster@seattle.gov`. District reps unchanged (they don't have collisions because each District N label has had only one current holder in our scrape window, but the new lookup is identically correct for them).

### Frontend — homepage hero + unified `/search` (legislation + municode) — committed 2026-04-27
Fills the hero gap left by the Rep Lookup move (PR #38) and adds a parallel-search results page that ties legislation and the Municipal Code together. The two are interlinked enough — bills cite SMC sections, SMC chapters reference legislative history — that one search box covering both matches users' actual mental model better than two separate ones.

**Hero (`LegislationHero.jsx`)** — mounted above `<ThisWeek />` on the homepage. Skyline background (`/static/images/SeattleSkyline.jpeg`, served from `frontend/public/`) with a `rgba(4,44,81,0.78)` overlay; centered title + subtitle + a pill-shaped white search input. Title: "Search Seattle Government." Empty submit → `/legislation` browse mode; non-empty → `/search?q=<encoded>`. Styles cribbed from the deleted `HeroSection.css` from the original Rep Lookup hero, scoped under `home-hero-*` for namespace hygiene. Background-image URL bumped from the old `/images/...` path (which would now hit the SPA catch-all because Vite's `base` is `/static/`) to `/static/images/SeattleSkyline.jpeg`.

**`/search` page (`Search.jsx`)** — fans out two parallel `Promise.all` requests against `/api/legislation/?q=` and `/api/smc/?q=` with `limit=5` each, renders two stacked sections — `Legislation (N)` and `Municipal Code (N)` — with a "View all N results →" link to the type-specific index when there are more than 5 hits. Debounced URL-synced search input on the page lets users refine without leaving. We don't try to merge ranking across types — there's no honest way to compare a bill's relevance to an SMC section's, so we stack instead. Empty `q` shows a "Type a keyword or citation above to begin searching" prompt.

Citation queries route naturally: `q=23.47A` returns 30 SMC sections (citation mode) + 5 legislation matches that mention the citation. Topical queries surface both: `q=tree` returns 21 bills + 186 SMC sections.

Reuses `LegislationCard` directly for the legislation section. SMC results use a 3-column row similar to `MuniCodeIndex`'s search list (number, title, chapter), styled under `search-smc-*`.

### Frontend — `/reps/` reorder, district pages, map↔card hover sync — committed 2026-04-27
Started as a section reorder and grew. Four things land together because they share the same scope (the `/reps/` page and how users get from map/lookup to rep info):

1. **Address lookup moved above the map.** It's the most goal-directed action on the page; leading with it matches user intent better than asking them to scroll past a map first. New `.reps-section--lead` modifier zeroes `margin-top` so the lookup sits flush under the header. Subtitle copy updated from "Click a district on the map…" to "Find your district representative by address, or browse the full council below."

2. **New `/reps/district/<number>/` page** showing the district + its rep + both at-large reps as click-through links to individual rep details. Replaces the inline lookup-result callout that used to render on `/reps/`. Backend: new `GET /api/reps/districts/<number>/` endpoint returning `{district, rep, at_large}`. Frontend: new `RepDistrict.jsx` component, route `/reps/district/:number`. Header bar uses the district's accent color as a left border for visual continuity with the map.

3. **Map polygon click → district page** instead of straight to a rep, and **hover on a polygon highlights the matching rep card** in the same color (`box-shadow: 0 0 0 2px <color>33` plus `border-color`). Address lookup also navigates to the district page on success. `DISTRICT_COLORS` lifted into `frontend/src/components/districtColors.js` so `CouncilMap` and `RepsIndex` stay in sync.

4. **District mini-map on the detail page.** New `DistrictMiniMap.jsx` renders a single-district close-up — Carto tiles, the district outline filled with its accent color, fitBounds-zoomed, no scroll-zoom or click handlers. Sister to `CouncilMap` (full council with click-through behavior). District detail endpoint now includes the same simplified geometry as the overview map (~10 KB per district), so visual continuity carries from the council overview through the district page. Mirrors the original `DistrictMap` behavior on the old homepage RepLookup result.

Pre-existing data quirk surfaced while testing the district endpoint: `_rep_row_to_dict`'s contact-detail lookup uses `OCDPerson.objects.filter(memberships__label=label).first()`, which can return any historical holder of e.g. "Position 9" — Dionne Foster's email currently shows as Sara Nelson's. Filed under Up next; not a regression and out of scope here.

### Frontend — `/reps/` council overview map + rep detail pages — committed 2026-04-27
Rep Lookup graduated off the homepage into a dedicated `/reps/` index, plus a chicago.councilmatic.org-style council map showing all 7 districts at once and per-rep detail pages. Closes both "Move Rep Lookup to its own index page" and the new "interactive map highlighting reps" idea in one PR.

**Backend** — three new endpoints under `/api/reps/`:
- `GET /api/reps/` returns `{districts: [{number, name, description, geometry, rep}], at_large: [{slug, name, district, ...}]}`. Geometry is GEOS-side simplified at ~5m tolerance (`preserve_topology=True`) — the unsimplified DB geometry remains for `ST_Contains` address lookup, so visual simplification can never route an address to the wrong rep. Total simplified payload ~141 KB across all 7 districts.
- `GET /api/reps/<slug>/` returns single-rep detail by `councilmatic_core_person.slug`, scoped to currently-serving members.
- Existing `POST /api/reps/lookup/` unchanged.

`is_current` lives on `councilmatic_core_person` via the raw-SQL ALTER from `seattle_app/migrations/0001`, which is why the new helpers drop to raw SQL via a shared `_query_current_council_members` helper. Rep dict construction unified through `_rep_row_to_dict` so list and detail endpoints serialize the same way.

`SimplifyPreserveTopology` from `django.contrib.gis.db.models.functions` isn't available in our Django version; switched to GEOSGeometry's Python-side `geometry.simplify(tolerance, preserve_topology=True)` per row, which is also cleaner (no Func annotation gymnastics).

**Frontend** — three new components and two new routes:
- `CouncilMap.jsx` — Leaflet map with all 7 districts as colored polygons (tab10 palette + brand navy for D7), hover tooltip showing district + rep name, click navigates to `/reps/<slug>`. Carto Voyager tiles. Includes a horizontal swatch legend below the map.
- `RepsIndex.jsx` — `/reps/` page: header + `<CouncilMap />` + district-rep cards grid + at-large section + address-lookup form (relocated from the homepage). At-large reps render in their own grid since they have no polygon to click.
- `RepDetail.jsx` — `/reps/:slug` page: eyebrow (district label) + h1 (name) + description + contact rows + external links (City Council profile, Office hours when available).
- New routes in `App.jsx` (`/reps`, `/reps/`, `/reps/:slug`); NavBar's `My Council Members` flipped from a `#my-council-members` hash stub to a real `Link to="/reps"`.

**Removed**: `RepLookup.jsx`, `DistrictMap.jsx`, `HeroSection.jsx` and their CSS — all three only referenced each other (HeroSection only inside RepLookup), so they're safe to delete after the move. The Carto tile switch on `DistrictMap.jsx` from PR #37 is preserved in git history but the file itself goes away here; the new `CouncilMap` was built using Carto from the start.

**Homepage** is now `<ThisWeek />` only — Rep Lookup left a gap in the hero space. The next Up-next item ("Legislation search bar in the homepage hero") fills it.

Verified: API endpoints return the expected shapes; `/api/reps/rob-saka/` → 200 with full detail, `/api/reps/nope/` → 404; production build clean (1741 modules, 4 s, ~436 kB JS / ~50 kB CSS); all SPA routes 200, including the new `/reps`, `/reps/<slug>`, and the previous routes still working.

### Frontend — swap OSM tile server for Carto Voyager — merged 2026-04-27 (PR #37)
RepLookup's district map was hitting `tile.openstreetmap.org` directly, which OSM's TOS prohibits for embedded third-party app use. Their infra rate-limits or 403s once a deployed app generates non-trivial traffic, breaking the map for users.

Swapped to Carto Voyager (`{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png`): no API key, free tier covers civic-scale traffic, neutral palette that matches the site, attribution to OSM + CARTO required (added to the Leaflet `tileLayer` config). Single-line change in `DistrictMap.jsx`. The file was removed in the immediately-following council-map PR but the Carto provider stayed.

### Municode — title and chapter names from PDF TOC — committed 2026-04-27
Closes the "title and chapter names" Municode follow-up filed during PR 3. The browse listings now read like a real table of contents: `Title 1 — GENERAL PROVISIONS — 6 chapters · 28 sections`, and chapter listings show `Chapter 1.01 — Code Adoption — 4 sections`.

New `CodeTitle(title_number, name)` and `CodeChapter(chapter_number, title_number, name)` models populated from the SMC PDF's Detailed Table of Contents (pages 149-168 of the 20260421 snapshot). Matches the Subchapter pattern — separate models keyed by the canonical number, looked up by FK-by-string in the API endpoints. Migration `0016` creates the tables.

New `extract_smc_toc` management command. Walks TOC lines with a small state machine: `Title <N>` heading → accumulate following non-header non-divider lines as the title name (with soft-hyphen folding for `PRESERVA-` / `TION` wraps); `(\d+(?:[A-Z])?\.\d+(?:[A-Z])?) <name> (<roman>) <page>` → chapter row; multi-line chapter names fold from a `<num> <name-head>` line into the next-line `<name-tail> <roman> <page>` continuation. Two regex bugs caught in the dry-run: trailing `\b` on `DIVIDER_RE` failed at non-word/non-word boundaries (after `Chapters:`/`(Reserved)`), letting those lines slip into the title-name buffer; `JUNK_RE` was anchored with `$` so footers like `TC-1 (Seattle 6-25)` (single line containing both fragments) missed the literal-line match — both fixed to use prefix/start-anchored matches. Inline title format (`Title 12A CRIMINAL CODE` on one line, common when column wrap fits) handled via the optional `(?:\s+(.+))?` group on `TITLE_RE`.

Output: 25 titles, 556 chapters parsed and persisted. All 22 titles that have sections in our DB get matched names; reserved titles (13, 19) are stored too (for future "browse including reserved" if we want it).

API surface threading:
- `/api/smc/tree/` returns `name` on each title and chapter.
- `/api/smc/titles/<n>/` returns the title `name` plus chapter names.
- `/api/smc/chapters/<n>/` returns `title_name` + `chapter_name`.
- `/api/smc/sections/<n>/` returns `title_name` + `chapter_name` (for breadcrumb context).
- `_title_neighbor` and `_chapter_neighbor` populate `secondary` on the prev/next pills with the title/chapter name (e.g. `Title 22 — BUILDING AND CONSTRUCTION CODES` instead of just `Title 22`).

Frontend: `.smc-toc-row` is now a 3-column grid (`<label> <name> <meta>`) used uniformly across titles, chapters, and appendices on the index and title pages. Stacks to 2-line layout below 600 px. Title detail page header switches to an eyebrow pattern (small navy mono "Title 23" → big h1 "LAND USE CODE"); chapter detail page does the same with "Chapter 23.47A" → "Commercial" → "Title 23 · LAND USE CODE" sub.

While in the model file, declared the trigram index `smc_section_number_trgm_idx` on the `MunicipalCodeSection.Meta.indexes` (it was created via `migrations.AddIndex` in 0015 but never declared on the model, so `makemigrations` kept proposing to remove it — would have bitten us on the next schema change).

### Municode — `/municode/` SPA index page + API + light-pass renderer — committed 2026-04-27
PR 3 of three for the `/municode/` build (closes the `/municode/` Up-next item). User-facing search + browse over the 7,435 parsed `MunicipalCodeSection` rows, plus title/chapter/section detail pages and the Title-15 appendix.

**Backend** — six endpoints under `/api/smc/`. The search endpoint splits behavior by query shape: a citation prefix (matches `^[0-9]+[A-Za-z]?(?:\.[0-9A-Za-z]+){0,2}$`, e.g. `23.47A`) does `section_number__istartswith` backed by the trigram GIN index; everything else hits the FTS path with `SearchQuery(q, search_type='websearch')` ranked by `SearchRank('search_vector', query)`. Citation routing is necessary because `to_tsvector('english', '23.47A.004')` produces `'23.47A.004'` as one atomic token (verified during the FTS spot-check) — partial citations can't reach it via FTS. Returned `mode` field tells the frontend which path ran. Optional `title=` / `chapter=` filters narrow either path.

`smc_tree` returns titles + chapter counts + appendix list for the browse skeleton (sections excluded — too numerous; chapter pages fetch them on demand). Title/chapter/section/appendix detail endpoints return everything the corresponding page renders, including the LLM summary fields (currently null until the summarize_smc_sections command lands). Appendix lookup keys off slugified label (`'I AND II'` → `'i-and-ii'`) so the `<slug:>` URL converter can match.

Title sort uses a numeric prefix tuple `(int(n), n)` so `1, 2, …, 9, 10, 11, 12A, 13` lands in document order, not lexicographic `1, 10, 11, 12A, 2, …`.

Migration `0015` enables `pg_trgm` via `TrigramExtension()` and adds `smc_section_number_trgm_idx` (`GinIndex(opclasses=['gin_trgm_ops'])`) on `section_number` — citation prefix queries now use the index instead of a sequential scan.

**Frontend** — five React Router routes plus a shortcut redirect:
```
/municode/                              → MuniCodeIndex (search + browse tree)
/municode/:slug                         → MuniCodeTitle (or 302 if slug contains '.')
/municode/:title/:chapter               → MuniCodeChapter
/municode/:title/:chapter/:section      → MuniCodeSection
/municode/:title/appendix/:label        → MuniCodeAppendix
```
The 1-segment route (`MuniCodeTitle`) decides between rendering a title page and redirecting to canonical 3-segment form by checking whether the slug contains a `.` (title numbers like `23` / `12A` never do; section/chapter citations always do). React Router's static-segment ranking puts `appendix` above `:chapter` for the 3-segment routes, so `/municode/15/appendix/i-and-ii` doesn't get caught by the chapter pattern. URL form `/municode/<title>/<chapter-short>/<section-short>` (e.g. `/municode/23/47A/004`) — title and chapter short forms reconstruct the full dotted identifier on the API side via `${title}.${chapter}.${section}`.

`SectionText` (light-pass renderer): the parser emits hard-wrapped lines at PDF column width (~50 chars, broken mid-sentence), so a `<pre>` render would be unreadable. Reflow logic joins consecutive non-marker lines with spaces and starts a fresh paragraph on each enumeration marker (`A.` / `1.` / `a.` matched by `/^([A-Z]\.|[a-z]\.|\d+\.)\s+/`). Three indent levels: A./B./C. → level 1, 1./2./3. → level 2, lowercase → level 3. Markers render inline at paragraph start (preserved as part of the legal text, not converted to bullets).

Plain-language summary panel renders only when `data.plain_summary` is non-null — placeholder for the upcoming summarize_smc_sections command, no UI churn needed when summaries land. Chapter listings get a small "Plain summary" badge per section that has one. NavBar gains a `Municode` entry between Legislation and My Council Members.

Verified: API smoke tests across all six endpoints (`q=short-term rental` → Chapter 6.600 at the top, `q=23.47A` mode=citation returns 30 sections, `q=23` mode=citation returns 1062 sections in Title 23, section/chapter/title/appendix detail all return complete payloads, missing keys 404). SPA routes all serve 200 from Django (which proxies to the prebuilt `dist/`), the production build compiles clean (1739 modules, 4 s, 432 kB JS / 49 kB CSS), and the served HTML references the new bundle hashes.

**Not browser-tested**: the rendered UI hasn't been visually verified end-to-end (no headless browser available in this session). Worth a manual click-through against the golden paths before the next thing lands on top of this: search → click result → breadcrumb back; browse → title → chapter → section; the `23.47A.004` shortcut redirect; the appendix page; pagination on a search with > 20 hits.

**Open follow-ups (filed as Up-next items below)**: title/chapter names (parser only captures section names today, not title or chapter labels — `"Title 23"` shows as a number, not "Land Use Code"); search snippets via `ts_headline` for FTS hits; in-chapter search box on the chapter page (the `chapter=` filter is wired in the API but not yet exposed in the UI).

### Municode — Postgres FTS infra on `MunicipalCodeSection` — committed 2026-04-27
PR 2 of the three-PR `/municode/` build. Adds a tsvector search column + GIN index to `MunicipalCodeSection`; the API endpoint and SPA page land in PR 3.

Implemented as a Postgres **generated column** (`GENERATED ALWAYS AS ... STORED`) rather than a trigger or a Django `save()` override. Generated columns are computed by PG itself on every insert/update of the source columns, so the vector stays in sync regardless of insertion path — Django ORM, parser `bulk_create`, raw SQL, fixtures, admin all benefit equally with zero application code. Requires PG 12+; we're on `postgis/postgis:14-3.2`.

Vector body weights `section_number` (A, the legal citation), `title` (B, the heading), and `full_text` (C, the body) using `english` config. Migration `0014` adds the column via `migrations.RunSQL` (Django's `AddField` doesn't speak `GENERATED ALWAYS AS`) with `state_operations=[AddField(...)]` so Django's migration graph stays consistent with the model. `migrations.AddIndex` builds `smc_section_search_idx` as a `GinIndex`. Model gains `search_vector = SearchVectorField(null=True, editable=False)` plus the `Meta.indexes` entry.

`django.contrib.postgres` added to `INSTALLED_APPS` for migration framework awareness of `SearchVectorField`/`GinIndex`.

Verified end-to-end: migration applies in ~6 s wall-clock (Django bootstrap dominates; PG fills the column inline during `ALTER TABLE` for all 7,435 existing rows — no `RunPython` backfill needed); column shows `is_generated='ALWAYS'` with the expected expression; GIN index exists; 7435/7435 rows have non-null vectors. Sample `SearchRank` query for "short-term rental" returns Chapter 6.600 (Seattle's STR chapter) `6.600.065 Summaries of short-term` → `License fees` → `License applications` → `23.44.051 Bed and breakfasts` — the kind of relevance ranking that motivated keeping this in-database rather than reaching for ES.

`pg_trgm` deferred to PR 3 (when the search endpoint actually needs fuzzy section-number lookup).

### Search — strip Elasticsearch + Haystack — committed 2026-04-27
Elasticsearch was plumbed in but not actually serving search: only `update_index` (run nightly) wrote to it, and the SPA's user-facing search bars (`/api/legislation/`, `/api/events/`) bypass it entirely with Postgres `Q(... __icontains=q)` queries. The legacy server-rendered `/search/` page existed via `councilmatic_search.urls` but the SPA never linked there. Net cost: a 1 GB ES container, the `bill_text.txt` packaging-bug surface we vendored around, and the daily `update_index` step that masked the cron env-loss outage in 2026-04.

Decision (after weighing options): rip ES now, plan to add Postgres FTS as part of the upcoming `/municode/` build (legal prose at 7.4k sections is well within PG FTS range; pgvector for LLM-driven retrieval composes naturally in the same DB). Three-PR plan: (1) this rip-out, (2) FTS infra on `MunicipalCodeSection` (search vector column + GIN index + trigger), (3) `/municode/` SPA index page + browse/detail.

Removed: `elasticsearch:7.14.2` service + `seattle_es_data` volume + `app.depends_on.elasticsearch` from docker-compose, `councilmatic_search` and `haystack` from `INSTALLED_APPS`, the `HAYSTACK_CONNECTIONS` block + `HAYSTACK_SIGNAL_PROCESSOR`, `councilmatic_search.urls` mount in `urls.py`, [seattle_app/search_indexes.py](seattle_app/search_indexes.py), the vendored `seattle_app/templates/councilmatic_search/templates/indexes/bill_text.txt`, the `update_index` step in `scripts/update_seattle.sh`, `SEARCH_URL` from `.env.example`, the `[all]` extras from `django-councilmatic` in `requirements.txt`, and ES references throughout `ARCHITECTURE.md` (Stage 4 Index section, troubleshooting, deployment checklist, performance section). Verified: `python manage.py check` clean; `/api/legislation/`, `/api/events/`, and SPA root all return 200 after restart; the old `/search/` URL now falls through to the SPA catch-all and renders `<NotFound />` client-side.

Operator follow-ups (not in the diff): drop `SEARCH_URL` from real `.env` files; `docker compose stop elasticsearch && docker compose rm -f elasticsearch && docker volume rm seattle_es_data` to reclaim the volume after merge; `pip install -r requirements.txt` (or rebuild the app image) to drop the `[all]` extras (haystack, elasticsearch7).

### Frontend — NavBar in header, site-wide footer, copy fix — merged 2026-04-26 (PR #33)
NavBar moved from a separate row below the Header into the Header itself, right-aligned beside the logo, so it shows on every route (not just the homepage). Dropped the `activeItem` prop in favor of `useLocation`-driven detection (`/legislation*` → `Legislation` active, etc.); hash-anchor stubs only highlight on the homepage. NavBar removed from `HomePage` since it's global now. NavBar's `.css` simplified to drop the standalone background/container — Header owns those. Mobile NavBar wraps via `flex-wrap`; a proper hamburger is deferred unless narrow-screen usability becomes a problem.

New `Footer.jsx` rendered in `App.jsx` outside `<Routes>` so every page inherits it. Contents: copyright (auto-current-year), GitHub link, "Powered by Councilmatic". Sticks to the bottom on short pages via `margin-top: auto` plus the existing `#root` flex-column.

Copy: "New Legislation" → "Recent Legislation" in ThisWeek's section header.

### Frontend — index breadcrumbs + clickable Header logo (far-left) — merged 2026-04-26 (PR #32)
SPA index pages had no built-in way back to the homepage. Added a breadcrumb (`This Week / <name>`) at the top of `LegislationIndex` and `EventsIndex` matching the detail-page pattern. Also made the Header logo + title a `<Link to="/">` so it works as a universal "go home" affordance from any page (homepage, indexes, detail) — hover shifts the title color, focus-visible adds an outline. Header container changed from `max-width: 1280px; margin: 0 auto` to `width: 100%` so the logo sits in the far-left viewport corner with just `1rem` padding, matching the convention on other Councilmatic sites.

### Frontend — events index + meetings → events rename — merged 2026-04-26 (PR #31)
Second SPA index page plus a full rename sweep. The council's calendar has multiple event types (committee meetings, council briefings, full council meetings, hearings) so "events" is the umbrella term and "meeting" only describes a subset. The API path was already `/api/meetings/` from a previous user-facing rename, so this PR finished alignment in one sweep: API paths/view-fns, component files (`MeetingCard`/`MeetingDetail` → `EventCard`/`EventDetail`), routes (`/events*`), labels (NavBar `Events`, page header, NotFound, breadcrumb, ThisWeek section title `Upcoming Events`).

New `events_index` endpoint (`q`, `time` ∈ {upcoming default, past, all}, `type`, `limit`, `offset`) returns paginated results plus `time_values` and `type_values` for the frontend dropdowns. **Type is derived from name** via `_classify_event` — Legistar doesn't expose a structured event type field. `Committee` is the fallback because some committee names come back truncated in the Legistar source itself (verified by hitting `EventBodyName` directly: `'Transportation and Seattle Public Utilities'` is missing the trailing word "Committee" in the upstream API, not a schema or pupa bug). Listing endpoints now also include `agenda_file_url`/`agenda_status`/`packet_url`/`minutes_file_url`/`minutes_status`/`legistar_url` per result so the frontend card can surface cancellations and let users open docs without clicking through (added `prefetch_related('sources')` to both list querysets).

`EventCard` got a color-coded type chip, a `Cancelled` badge with strike-through title when `agenda_status === "Cancelled"`, and a row of doc-link pills (Agenda / Packet / Minutes / Legistar ↗) at the bottom — only links that have URLs render. CSS class names (`.meeting-card-*`, `.mtg-detail-*`) deliberately weren't renamed: internal styling churn for no user-visible benefit, filed as a follow-up.

### Frontend — legislation index page (`/legislation/`) — merged 2026-04-26 (PR #30)
First of the three SPA index pages. New `GET /api/legislation/` endpoint with `q`/`status`/`limit`/`offset` params returns paginated, filtered results plus `total_count` and the valid `status_values`. Search matches `identifier` OR `title` (case-insensitive `Q` filter); status filter reverse-maps the normalized label (e.g. `"Passed"`) to all raw `MatterStatusName` values that map to it via `_STATUS_LABELS`. Invalid status values short-circuit to `qs.none()` rather than silently ignoring the param.

Frontend `LegislationIndex` component: debounced search (300ms), status dropdown, "Previous / Page X of Y / Next" pagination. URL-synced state via `useSearchParams` so filters and page are bookmarkable and survive browser back/forward. Reuses the existing `LegislationCard`. NavBar's `Legislation` entry converted from a `#legislation` hash stub to a real React Router `Link` to `/legislation` (other entries stay as homepage hash anchors until those sections ship — NavBar now mixes `Link` and `<a>` based on item shape). `NotFound` legislation variant updated from `/` to `/legislation` (carryover from PR #16's note).

`LegislationDetail` header: replaced the single "Back to This Week" link with a breadcrumb (`This Week / Legislation / <identifier>`). When the user arrives via a card on the index, the index's URL params are stashed in `location.state.backToSearch` so the breadcrumb's `Legislation` link returns to the same filtered/paginated view rather than a fresh search. Direct deep links and cards rendered outside the index (e.g. ThisWeek) have no state and fall back to a fresh `/legislation`.

### Scheduler — vendor missing `bill_text.txt` haystack template — committed 2026-04-26
The `update_index` step in the daily scrape (step 3 of `update_seattle.sh`) was crashing with `TemplateDoesNotExist: councilmatic_search/templates/indexes/bill_text.txt`. `councilmatic_search.search_indexes.BillIndex` (in the `django-councilmatic[all]==5.0` package, installed from `https://github.com/datamade/django-councilmatic/archive/refs/heads/5.x.zip`) hardcodes that exact `template_name` but the wheel built from the 5.x branch ships without the template directory at all — packaging bug in `MANIFEST.in` / `pyproject.toml`. The template exists in the upstream git source.

This was a pre-existing bug, not visible until the env-loss fix below let cron jobs progress past step 1. Since nothing surfaces a missed cron run, the index was silently stale for whatever window the env-loss outage covered.

Fix: vendored the template at `seattle_app/templates/councilmatic_search/templates/indexes/bill_text.txt` (the doubled `templates/` directory matches the BillIndex's `template_name` exactly so Django's app-dirs loader resolves it). Content copied verbatim from the upstream `5.x` branch. Verified `python manage.py update_index` exits 0 and indexes all 378 bills.

### Scheduler — fix env-loss in cron jobs (DATABASE_URL etc.) — committed 2026-04-26
Daily 2 AM UTC scrape was firing on schedule but crashing immediately with `OperationalError: connection to server at "localhost" (::1), port 5432 failed`. Root cause: cron sanitizes the environment of every job it launches, so vars from `env_file: - .env` (set on the container's PID 1) weren't visible to the cron-launched script. Django's settings then fell back to `localhost:5432` instead of the `postgres` service hostname, and the connection died. The container itself, the schedule, the script, and the crontab were all fine — silent data-pipeline outage hidden behind a noisy stack trace in `/var/log/cron/sync.log` that nothing was reading.

Fix: new `scripts/scheduler-entrypoint.sh` snapshots the container env to `/etc/cron-env` at startup (Python writes properly-quoted `export KEY=value` lines via `shlex.quote`, so values with spaces/quotes/`$` are safe), then `crontab` reinstalls the crontab from the volume-mounted `scheduler-crontab` (so future crontab edits don't need a Dockerfile rebuild), then starts cron and tails the log. Updated `scheduler-crontab` prepends `. /etc/cron-env &&` so each cron-launched job picks up the snapshot. `docker-compose.yml` swaps the inline `sh -c "cron && tail ..."` for `sh /app/scripts/scheduler-entrypoint.sh`.

Verified live: cron fired at 02:00 UTC immediately after the restart, ran the script successfully, pupa scraped events and bills (the only errors logged were pre-existing data-resolution warnings — pseudo-id mismatches for sponsor names like `'Cathy Moore'` / `'Tammy J. Morales'` and Bill identifiers like `'Appt 03471'` / `'Inf 2874'` that haven't been scraped yet — not infrastructure failures).

Follow-up commit `e6efd8d` set `TZ=America/Los_Angeles` (env on the scheduler container only) plus `CRON_TZ=America/Los_Angeles` in the crontab so the schedule fires at 02:00 Pacific (overnight Seattle) instead of 02:00 UTC (7 PM PDT day before). Other containers stay in UTC. DST handled by zoneinfo.

### Frontend — meeting agenda items, documents, and agenda packet — merged 2026-04-26 (PR #29)
Backend scraper enriches each event with substantive agenda items (skipping procedural lines like "Call to Order" / "Roll Call"), per-item attachments, and Bill links via pupa's `add_agenda_item` / `add_bill`. Agenda + Minutes PDF URLs come from Legistar API event fields; the Agenda Packet URL isn't exposed via API and is scraped from the Legistar HTML page (regex on `id="ctl00_ContentPlaceHolder1_hypAgendaPacket"` href). API extension: `GET /api/meetings/<slug>/` now returns `agenda_items[]` (with `matter_file`, `matter_type`, `matter_status`, `action_text`, `bill_slug`, `attachments[]`), `agenda_file_url`, `agenda_status`, `packet_url`, `minutes_file_url`, `minutes_status`. Frontend: four new components in `MeetingDetail.jsx` (`MatterChip` for CB/Res/Inf badges, `DocIcon` for PDF/DOC affordances, `AgendaDocButtons` for the top-of-page Agenda/Packet/Minutes pill buttons, `AgendaItemRow` for the numbered list with attachments and React Router links to `/legislation/<bill_slug>` for matched bills).

Originally drafted in worktree `claude/zealous-tharp` at commit `baa719c` (2026-02-24, Sonnet 4.6); cherry-picked clean (single auto-merge in `MeetingDetail.jsx`) onto current `main`. Worktree + branch removed post-merge. Verified end-to-end on Human Services committee meeting (5 substantive items, packet URL, attachments, bill linkage to `res-32191`).

### Parser — recover 3 missing sections via citation lead-ins, figure-caption boundary, Reviser's-note strip — committed 2026-04-26
Three independent fixes, each addressing one section in the 5-small-missing pool. All verified via focused dry-runs.

1. **`23.76.067 Amendments to Title 23 to implement RCW 43.21C.420 (SEPA)`** (p3725) — title contains `43.21C.420`, a section-number-shaped substring that matched `EMBEDDED_SECTION_RE`. The ghost-citation guard from PR #17 (`LEGITIMATE_SECTION_CITATION_RE`) only accepted `Section(s) X.Y.Z` lead-ins, so `RCW 43.21C.420` and `U.S.C. X.Y.Z` lead-ins were rejected as ghost headings. Extended the regex to accept `RCW` and `U\.S\.C\.` alongside `Section(s)`. Real ghosts (the ORDINANCES CODIFIED appendix list `'ChartA, 23.50.012 ChartA, ...'`) still have no lead-in and remain rejected. Clears 1 `ParseValidationIssue` row.

2. **`25.24.030 Commission created.`** (p4362) — `prev_line` was `'Exhibit "A"—Pike Place'`, a figure caption ending in lowercase prose without terminal punctuation. `_is_section_boundary` rejected it and the heading was silently dropped. Fix: treat lines starting with `Exhibit `, `Map `, `Table `, `Chart `, or `Figure ` as boundaries. These are layout labels for figure captions inserted between sections — body prose almost never starts with these words immediately before a `SECTION_RE`-matching line.

3. **`23.50A.160 Structure height exceptions and additional restrictions`** (p3246) — Reviser's notes are full-page-width editorial annotations about codification history, but our column-aware extraction splits them at page midpoint, producing reading-order garbage like `'reference has been codified as subsection'` (mid-sentence fragment, no terminal punctuation) immediately before the next section's heading. The boundary check rejected the heading and the section was silently dropped. Fix: new `_strip_revisers_notes` helper drops lines from a `Reviser's note` marker forward until the next `SECTION_RE` / `CHAPTER_HEADING_RE` / `SUBCHAPTER_LINE_RE` heading or end of page. The note above-section keeps its body (the `(Renumbered from X; Ord. Y, § Z, YEAR.)` stamp closes it before the note begins); the next section sees the pre-note line as `prev_line`. Trade-off accepted: editorial notes are not normative section text, and column-jumbled readings aren't useful anyway. An earlier draft (column-break sentinel injected between left/right columns) was reverted — the offending `prev_line` was inside the right column, not at the column boundary, so the sentinel didn't help.

Also resolved this session: `12A.14.160` confirmed nonexistent (TOC for chapter 12A.14 jumps from `.150` to `.175`, no PDF body presence on p1594/p1595, no `ParseValidationIssue` row) — dropped from the missing list. `23.48.235` deferred — PDF lacks a clean section heading (number lives in running header `'SEATTLEMIXED 23.48.235'`, title `'Upper-Level Setbacks'` floats after a `'Map A for 23.48.235'` figure caption); probably a PDF source issue, kept as Up-next.

Full-PDF re-parse on `93cb885`: 7,430 → 7,435 sections (+6 new − 1 orphan), 31 → 28 `ParseValidationIssue` rows (-3). Two bonus recoveries beyond the 3 targeted: `23.50.018 'View corridors'` (separately-flagged in PR #28's note as missing-from-parse) and `22.602.050 'Fees for certain inspections'` (brand new discovery) — both likely Reviser's-note-strip side effects. One orphan deleted: `10.09.020`, a stale phantom from an older parse cleaned up by `--allow-deletes`.

### Parser — anchor § boundary check on `Ord. + §`, not § alone — merged 2026-04-26
PR #28's `_is_section_boundary` accepted any line containing `§` as a boundary. The full-PDF re-parse on the merged PR surfaced two synthesized phantoms in chapter 25.32 (`25.32 V '(Litter Control Code) and §§ 21.36.400'`, `25.32 VI 'of Chapter 23.69; amends'`) where body cross-references contain `§` mid-sentence. Their prev_lines (`'new § 23.54.016; renumbers Subchapter V to be'`, `'adds §§ 3.14.700-3.14.750 and 5.78.190; amends'`, `'(Miscellaneous Provisions) before § 21.36.180,'`) describe ordinance actions in prose without the `Ord.` token, but passed the loose `§` rule and let the cross-references on the following lines fire as inline body subchapter dividers, creating synthesized drafts with garbage names.

First refinement attempt — require `§` AND trailing `,` or `;` — was both too narrow (the legitimate 5.48.050 recovery has prev `'change]; Ord. 118397, § 84, 1996 [department/'` ending on `[department/`, not on `,;`) and not narrow enough (the 25.32 V cross-ref `'(Miscellaneous Provisions) before § 21.36.180,'` ends with `,` and still passed). Final rule: `"§" in stripped and "Ord." in stripped`. Real ordinance citation blocks always have an `Ord.` token within the wrapped span; body cross-refs talking about `§ X` of an unnamed action don't.

Verified: 23.50 III on p3209 still fires; 25.32 chapter (pp 4440-4480) produces zero subchapter dividers; 5.48.050 will be re-emitted (prev contains both `Ord.` and `§`). DB phantom rows are cleaned up automatically by the next full re-parse via `_cleanup_orphan_subchapters` (they aren't referenced by any divider firing).

### Parser — recover 23.50 III body sections + 21.36 IV `(Reserved)` name (PR #28)
Two distinct bugs surfaced by the audit of the 9 "declared-but-empty" subchapters; 8 of those 9 were legitimate Reserved/empty placeholders in the SMC, but 23.50 III and 21.36 IV were real parser bugs.

1. **23.50 III — body divider failed boundary check on Ord. citation continuation.** Chapter 23.50's body divider for Subchapter III "Development Standards in All Zones" sits on p3209 with `prev_line = '115135, § 1, 1990; Ord. 115002, § 11, 1990; Ord. 113658,'` — a column-split tail of a multi-line `(Ord. ..., § ..., YEAR; Ord. ...)` block. The line ends with `,` not `)`, so `_is_section_boundary` returned False, `_TocScanner.observe` returned None, the divider didn't fire, and 19 declared sections of III got stamped to subchapter II (the previously-active key). Result: 34 of 62 `ParseValidationIssue` rows came from this single bug. Fix: extend `_is_section_boundary` to recognize lines containing `§` as boundaries — `§` is a legal-citation marker that doesn't appear in SMC body prose, so its presence on a non-terminal line is a reliable continuation signal. Verified spot-checked by sampling sections that reference `§`; all such body uses also include `Ord.` / `RCW` / `U.S.C.` (citations) and end with terminal punctuation (which already passed the existing checks).

2. **21.36 IV — TOC absorb loop swallowed name-continuation lines.** Body parser at `_walk_sections:927` absorbs up to 2 continuation lines after a Subchapter heading so the next section's boundary check sees the divider as `prev_line`. But the absorb loop only incremented `i` — it never passed the absorbed lines through `_TocScanner.observe`. So in chapters with multi-subchapter TOC layouts (`Sections:` / sections / `Subchapter III` / `Flow-Control Special Provisions` / sections / `Subchapter IV` / `Miscellaneous Provisions (Reserved)` / `Subchapter V`), the bare-divider-then-name TOC pattern lost the name line: the TOC scanner saw the bare `Subchapter IV` divider (state→IN_SUBCHAPTER_NAME), then the next observed line was `Subchapter V` (finalized IV with empty name). When the body inline divider `Subchapter IV Miscellaneous Provisions` later fired with name truncated by the body's wrap, the existing-draft branch saw an empty name and clipped to `'Miscellaneous Provisions'` (no `(Reserved)`). Fix: in the absorb loop, call `observe(absorbed_line, page_num, prev_for_absorbed)` so the TOC scanner can accumulate the name. Side effect (good): all multi-subchapter chapters that had names truncated by this bug will pick up correct names on the next re-parse.

Focused re-parses on chapter 21.36 (pp 2339–2362) and chapter 23.50 (pp 3193–3265) verify both fixes:
- 21.36 IV: name now `'Miscellaneous Provisions (Reserved)'` (was `'Miscellaneous Provisions'`).
- 23.50 III: name now `'Development Standards in All Zones'` (was empty); 16 of 19 declared sections correctly stamped (was 0). Remaining 3 missing are pre-existing: 23.50.002 (TOC scanner mis-records body-shaped section line as TOC entry of the last-active subchapter — separate bug), 23.50.018 and 23.50.027 (sections missing from the parse entirely; the 6-small-missing pool grows by 2).

`ParseValidationIssue` total: 62 → 35 (-27 in the focused ranges alone). A full-PDF re-parse to propagate the fixes to all chapters with multi-subchapter TOC layouts is filed as Up-next.

The 8 legitimately-Reserved subchapters surfaced by the audit (`2.04 V`, `4.72 II`, `4.76 I`, `10.08 II`, `20.60 I`, `21.36 IV` post-fix, `23.69 III`, `25.28 I`) produce zero validation noise (declared=[] + actual=[] cancel out) and need no further action.

### Parser — exit AFTER_CHAPTER state on first lowercase line — merged 2026-04-26 (PR #27)
Even with the orphan-subchapter cleanup wired up correctly (PRs #25/#26), the phantom `25.32 VI 'of Chapter 23.69; amends'` kept reappearing on every re-parse. Root cause: `_TocScanner` has an `AFTER_CHAPTER` state entered when a `Chapter X.Y` heading is matched and exited when a `Sections:` marker arrives. Real chapters always reach `Sections:`. But chapter 25.32 is table-only (Historical Landmarks) — no `Sections:` marker — so the scanner stayed in `AFTER_CHAPTER` for the entire chapter. The body cross-reference `'Subchapter VI of Chapter 23.69; amends'` on p4449 then matched `SUBCHAPTER_LINE_RE` and passed the `in_toc_state` guard (because `AFTER_CHAPTER` counts as TOC state), creating the phantom draft fresh on every parse. Once created, `_flush_unreferenced_drafts` added it to `_subchapter_cache`, so orphan-cleanup couldn't see it as orphan.

Fix: when in `AFTER_CHAPTER` state and a line containing any lowercase character appears, transition to `IDLE`. Chapter name continuations are all-caps (`ENVIRONMENTAL POLICIES AND PROCEDURES`), so legitimate chapters reach `Sections:` before any lowercase line. Verified: chapter 25.05 still detects all 11 subchapters (I–XI); chapter 25.32 produces zero drafts (was 1 phantom).

### Parser — scope orphan-subchapter cleanup by title, not chapter — merged 2026-04-26 (PR #26)
PR #25's `_cleanup_orphan_subchapters` scoped candidate rows by `parsed_chapters` (chapters where this run emitted ≥1 section). But chapter 25.32 is table-only — no section is ever emitted there — so it never appears in `parsed_chapters`, so subchapters in 25.32 were invisible to cleanup and the `25.32 VI` phantom survived every re-parse. Switched scope to `parsed_titles` (matching `_cleanup_orphan_sections`) and derive title from `chapter_number` via `split('.')`. The `Subchapter` schema has no `title_number` column, but `chapter_number` always starts with `title_number` followed by a dot (`'25.32' → '25'`, `'23.47A' → '23'`, `'12A.14' → '12A'`).

Side note: `23.47A I 'General Provisions'` was correctly identified as a phantom and deleted by PR #25 — verified no `Subchapter I` line exists anywhere in chapter 23.47A's pages (2920–2990). Its 18 `declared_section_numbers` were phantom data from the same old buggy parse. The 18-issue `ParseValidationIssue` drop was real cleanup, not hidden regressions.

### Parser — fix Subchapter orphan-scope key index — merged 2026-04-25 (PR #25)
PR #24's `_cleanup_orphan_subchapters` built `parsed_chapters` from `key[0]` (title_number, e.g. `'25'`) and filtered `Subchapter` rows where `chapter_number IN parsed_chapters`. But `chapter_number` is e.g. `'25.32'`, not `'25'`, so the `IN` filter matched nothing and zero orphans were ever deleted. Caught when the post-merge re-parse logged `Orphan subchapters deleted: 0` even though the known phantom `25.32 VI of Chapter 23.69; amends` was still in the DB. Use `key[1]` (chapter_number) so the `IN` filter matches.

### Parser — Subchapter cleanup: period-after-roman regex + orphan deletion — merged 2026-04-26 (PR #24)
Review of the 17 synthesized subchapters surfaced two issues:

1. **Chapter 25.10 / 25.12 / 25.28 / 5.56** use a non-standard TOC layout where the divider is `Subchapter I.` (period after the roman) instead of `Subchapter I`. `SUBCHAPTER_LINE_RE` required `^Subchapter X\s*$` and didn't match the period variant, so the TOC scanner never registered these subchapters — bodies later created `synthesized` rows instead of `official` ones (which skip validation). Made the `.` optional in the regex; verified Chapter 25.10 now produces 5 official subchapters (was 4 synthesized).
2. **Phantom `25.32 VI`** (name `'of Chapter 23.69; amends'`) lingered as a stale row from an older parse where body text matched `SUBCHAPTER_LINE_RE` (the cross-reference `'... renumbers Subchapter V to be Subchapter VI of Chapter 23.69; amends ...'`). The current TOC scanner correctly rejects body cross-refs via the boundary check, but the row from the older parse persisted because no Subchapter-orphan cleanup existed (PR #19's `--allow-deletes` only handled `MunicipalCodeSection`). New `_cleanup_orphan_subchapters` mirrors that pattern: scoped to chapters where this run emitted ≥1 section, deletes any `Subchapter` row not in `_subchapter_cache` (the set of subchapters this run touched). Cascade drops `ParseValidationIssue` rows linked to the subchapter; sections lose their `subchapter` FK to NULL via `SET_NULL`.

Side effect: making formerly-synthesized subchapters "official" surfaces real TOC-vs-body mismatches that were previously hidden (validation only runs on official subchapters). Expect `ParseValidationIssue` count to rise after the next full re-parse — that's a visibility improvement, not a regression. Mixed-line TOC entries with embedded subchapter dividers (`25.10.110 Applicability. Subchapter II. Definitions`) are not handled by the regex change and remain as a follow-up.

### Parser — capture Title appendix as a new model + fix `15.91.045` bleed — merged 2026-04-26 (PR #23)
Triage of the 10 oversized 30-50k-char sections found 9 legit (substantive long sections like SEPA `25.05.675` Specific environmental policies, alphabetical-definitions `23.84A.036 S`, parking standards `23.54.030`) and 1 buggy: `15.91.045 Additional relief.` was 44778 chars but its real body is ~283 chars — it was accreting Title 15's parks/scenic-routes appendix (pages 2047-2086+, referenced by SEPA) because the parser had no terminator for `APPENDICES I AND II TO TITLE 15`-style headings. Rather than just terminate the section and drop the appendix content, we capture it as a `TitleAppendix(title_number, label, full_text, source_pdf_page)` row keyed by `(title_number, label)`.

New: model `TitleAppendix`, migration 0013, `APPENDIX_HEADING_RE`, `ParsedAppendix` dataclass, appendix-mode in `_walk_sections` (terminates current section, accumulates body until the next chapter heading, deduplicates the running header that repeats `APPENDICES I AND II TO TITLE 15` on every appendix page), `_persist_appendix`, dispatch in `handle()` via `isinstance(record, ParsedAppendix)`. Verified end-to-end on Title 15 → Title 16 transition (pages 2040-2095): `15.91.045` shrinks to 283 chars (real body), one `TitleAppendix(title='15', label='I AND II', chars=43105, page=2047)` row created. Title 16 chapter heading correctly closes the appendix.

Survey: only Title 15 has appendix-style headings in the SMC; the model handles other titles automatically if they ever add appendices.

### Parser — figure-page boundary + tighten column-split header strip — merged 2026-04-26 (PR #22)
Two fixes that together recover 11 of the 17 sections the PR #21 re-parse silently orphan-deleted:

1. **Per-page boundary reset.** `_walk_sections` carried `prev_line` across page boundaries, so a body section heading at `L0` of a page failed `_is_section_boundary` whenever the prior page ended mid-citation or with a layout label (`'... Ord. 125291, § 6,'`, `'Exhibit 23.64.004B'`, `'for 23.48.225'`). Reset `prev_line = None` at the start of each page — body prose that genuinely wraps across pages is unaffected because emission only fires for `SECTION_RE`-matching lines, and those only legitimately appear at line 0 if the new page begins a new section. Recovers `23.48.230` (7.8k chars), `23.64.006` (1.9k).
2. **Tighter column-split header strip.** PR #20's `_strip_layout_artifacts` was unconditionally skipping the bare-section-number line PLUS the next line at the start of the right column. On p2956 the next line is a section-name continuation (`'Specific Areas: Interbay'`) that should be stripped, but on pages like p1122 the next line is body wrap (`'tion and payments for services via the internet'`) — silently eating the body of `8.37.020` and similar. Now only strips the next line if it looks like a header continuation: capital-start, ≤50 chars, no terminal punctuation, not enumerated. Recovers `8.37.020` (20k chars), `8.39.150` (5.5k), `8.39.190` (1k), `8.38.010`, others.

Result: 7409 → 7421 unique sections (11 recovered, no regressions; +101 net since the pre-PR-#21 baseline). All 4 PR #20 recovery cases (`23.47A.002`, `23.47A.010`, `23.47A.040`, `23.54.015`) still emit. Six small losses (≤ 1k chars) remain — filed as Up-next.

### Parser — bound TOC fold to prevent body-into-title runaway — merged 2026-04-26 (PR #21)
PR #20's `_fold_toc_name_wraps` exited TOC mode only on `ENUMERATED_BODY_RE` (`A. ` / `1. `). Chapters whose body sections start with plain prose instead of enumerated subsections — Title 1 ch.1.03 was the canary, where `1.03.010`'s body opens with `'To maintain the records and laws of the City...'` — never tripped the exit signal, so the entire body folded into the last TOC entry's title until the next section heading. Crashed psycopg2 with a `varchar(500)` overflow on the first persist. Plus the heuristic was too tight on capital-starting wraps (rejected real continuations like `'Code reviser to revise laws'`), causing first-section losses in chapters with em-dash compound TOC entries.

Fixes: per-section caps (`_TOC_MAX_FOLD_LINES=3`, `_TOC_MAX_TITLE_CHARS=200`, `_TOC_MAX_WRAP_LINE_CHARS=50`) plus a `_looks_like_toc_continuation` heuristic that accepts any-length lowercase continuations and capital-starting continuations up to 35 chars. Verified Title 1 (28 emits vs 25 in DB, +3 newly-recovered, 0 lost) and Title 23 (1050 emits vs 1035 in DB, 24 recovered including all 4 PR #20 targets, 9 losses of which 6 look phantom and 3 substantive). The 3 substantive Title 23 losses are filed as a separate Up-next item — they're a different bug class (body heading at L0 of a page where the prior page is a sparse figure-only layout page whose tail breaks the boundary check).

### Parser — recover missing sections via TOC-fold + boundary fixes — merged 2026-04-25 (PR #20)
The WORK_LOG had flagged "recover real `23.54.015` and `23.47.004`" as a presumed table-extraction problem; investigation showed the headings were never lost to tables — the parser was emitting them but `_is_section_boundary` rejected them because the prev_line was a layout artifact. Four distinct failure modes uncovered, each fixed:

1. **Soft-hyphen TOC wraps** — last TOC entry's name wrapped via soft hyphen, leaving the wrap continuation as prev for the first body section. New `_fold_soft_hyphens` joins wraps where line N ends with `-` and line N+1 is a lowercase non-heading continuation.
2. **Multi-line non-hyphen TOC wraps** — `23.47A.040`'s TOC entry wraps to 4 lines without soft hyphens. New `_fold_toc_name_wraps` runs in TOC mode (between `Sections:` marker and the first enumerated body subsection like `A. ` / `1. `), folding every name-continuation line into its preceding section-shaped line. Bounded by per-section caps (`_TOC_MAX_FOLD_LINES=3`, `_TOC_MAX_TITLE_CHARS=200`, `_TOC_MAX_WRAP_LINE_CHARS=50`) plus a `_looks_like_toc_continuation` heuristic — needed because chapters like Title 1 ch.1.03 have body sections that don't start with enumerated subsections, so the original ENUMERATED_BODY_RE exit signal alone let the fold runaway and crash psycopg2 with a varchar(500) overflow.
3. **Footers with `.` in chapter-page identifier** — `(Seattle 9-23) 23-180.2` wasn't matched by `FOOTER_RE` (the `.` broke the trailing `[\s\d\-]*$`). Extended to `[\s\d\-\.]*`.
4. **Layout labels and column-split running headers** — lines like `23.47A Map Book A` (between TOC and body) and the `23.47A.009` + `Specific Areas: Interbay` pair (column-split right-half running header) leaked through. New `_strip_layout_artifacts` drops both: `LAYOUT_LABEL_RE` matches "X.Y Map Book/Table/Chart Z", and a bare section-number at the start of the right column triggers a 2-line skip.

Recovered sections (verified via dry-run on pages 2920–3320): `23.47A.002`, `23.47A.010`, `23.47A.040`, `23.54.015`. The fix is general — any chapter that fails for the same reasons will now emit. The `23.47.004` mention in the original WORK_LOG note was a confusion: no section by that number exists; the ghost we deleted in PR #17 had borrowed those digits from a citation list. The real `23.47A.004` was already in the DB.

Side effect: `_persist`'s "text changed" branch will fire on most existing sections during the next full re-parse because the folded lines change `full_text`. LLM summary fields will be cleared (none generated yet anyway). Filed table-aware extraction as a follow-up Up-next item.

### Parser — orphan-section cleanup — merged 2026-04-25 (PR #19)
New `--allow-deletes` flag on `parse_smc_pdf`. The parser now tracks the (title, chapter, section) tuples it emits during a run and, when the flag is set, deletes any `MunicipalCodeSection` rows in the parsed titles that weren't in that set — i.e. orphans left over from earlier buggy parses (the ghost `23.47.004` / `23.54.015` we had to manually `DELETE` after PR #17/#18). Cascade drops `SectionOrdinanceRef` rows; `LegislationSummary` M2M unlinks; `subchapter` FK is `SET_NULL` on the section side so subchapters aren't touched. Gated to full-PDF parses only — refused with `--dry-run`, `--limit`, or any non-default `--start-page`/`--end-page` since partial ranges can't safely tell which titles are fully covered. Each deletion is logged with `style.WARNING` for transparency. Runs before validation so `ParseValidationIssue` reflects the cleaned state.

### Parser — gate `extract_text()` fallback to transition pages — merged 2026-04-24 (PR #18)
PR #17's `_extract_page_lines` fallback called `page.extract_text()` on every page where no `CHAPTER_HEADING_RE` matched — which is most pages. `extract_text()` re-runs the full layout pipeline, so this roughly doubled per-page work and made a full re-parse churn for hours. New `CHAPTER_FRAGMENT_RE` matches a bare `Chapter` line or a bare chapter-number like `25.32`; the fallback only fires when such a fragment is present AND no `CHAPTER_HEADING_RE` line matched. Body pages have neither, so the fast path is restored. Caught when the user noticed the re-parse churning on Title 15 like before the parser improvements.

### Parser — section-boundary leak (catastrophic) — merged 2026-04-24 (PR #17, perf hotfix #18)
Fixed the three catastrophic over-sized sections. Two distinct bugs:
1. **`Chapter 25.32` not detected** because two-column extraction fragments full-width chapter headings ("Chapter" alone in one column, "25.32" in the other). Chapter-flush at `_walk_sections` never fires, so 60+ pages of `25.32 TABLE OF HISTORICAL LANDMARKS` table content kept appending to `25.30.130`. Fix: in `_extract_page_lines`, when a `CHAPTER_FRAGMENT_RE` match exists but no full `CHAPTER_HEADING_RE` line, recover the heading from `extract_text()` (which doesn't column-split) and inject at the top. Hotfix #18 added the fragment gate so the expensive `extract_text()` only runs on transition pages, not every body page.
2. **Ghost heading from citation list** — body text like `23.47.004 ChartA, 23.50.012 ChartA, ...` in the "ORDINANCES CODIFIED" appendix matched `SECTION_RE`, creating a phantom section. Fix: new `EMBEDDED_SECTION_RE` + `LEGITIMATE_SECTION_CITATION_RE` reject titles that contain a section-number-shaped substring without a preceding `Section(s) X.Y.Z` lead-in. Real titles like `Penalty for violation of Section 3.30.050.` keep the lead-in and pass through.

Post-merge re-parse (2026-04-24): `25.30.130` shrank 280k → 177 chars; pages 4445–4495 (the ghost zone) emit zero sections; full PDF parse went from 478 `ParseValidationIssue` rows → 115, declared-but-empty subchapters from 37 → 11. The two ghost rows (`23.47.004`, `23.54.015`) were left in the DB as orphans because the parser is update-or-create only — manually `DELETE`d. Promoted "add orphan-cleanup to parser" as a follow-up Up-next item.

### Frontend — bad-slug 404 → kind-aware NotFound — merged 2026-04-24 (PR #16)
`LegislationDetail` and `MeetingDetail` now check for HTTP 404 from the API and render `<NotFound />` instead of the "Could not load: HTTP 404" error text. `NotFound` gained a `kind` prop with three variants — `legislation` ("Legislation not found" → recent legislation), `meeting` ("Meeting not found" → upcoming meetings), and the default generic ("Page not found" → This Week). The wildcard `<Route path="*">` in `App.jsx` keeps using the generic variant.

### Parser — NEPA/SEPA acronym titles — fixed in PR #12
The "NEPA/SEPA short-title bypass" Open thread was already resolved in `a7c4cc0` via a precise `is_acronym_title` check at `parse_smc_pdf.py:588-592` (`0 < len(bare_title) <= 6 and isalpha() and isupper()`). Cleaner than expanding the generic short-title bypass from `<= 3` to `<= 4`, which would have admitted noise like `"Co2."` or `"12-1"`. Entry was stale on the work log — surfaced 2026-04-24 during quick-wins triage.

### Frontend — SPA NotFound route — merged 2026-04-24 (PR #15)
Added `frontend/src/components/NotFound.jsx` (+ CSS) and wired `<Route path="*" element={<NotFound />} />` in `App.jsx`. Unknown SPA paths now render a styled 404 page instead of just the Header over an empty body.

### Frontend — retire `django-webpack-loader` — merged 2026-04-24 (PR #14)
Removed `webpack_loader` from `INSTALLED_APPS` + `WEBPACK_LOADER` block; deleted `IndexView`, `home_page.html`, root `package.json`/`package-lock.json`, `webpack.config.js`, `webpack-stats.json`; dropped the `webpack` service + `seattle_node_modules` volume; removed `django-webpack-loader` from `requirements.txt`. `base.html` kept (stripped of webpack bits) for `404.html`/`500.html`.

### Frontend — Vite/React cutover (path A) — merged 2026-04-24 (PR #13)
Vite `base: '/static/'`; new `react_app` view serves `frontend/dist/index.html` for `/` and any unmatched path. `urls.py` restructured: kept `admin/`, APIs, `search/`, `cms/`, `documents/`; dropped wagtail's `""` catch-all so React owns the SPA routes.

### Parser — subchapter TOC + validation — merged 2026-04-24 (PR #12)
Subchapter schema, TOC scanner, body FK stamping, landmark `designation_type` backfill, subchapter divider bug fix. Full re-parse: 9,930 sections, 202 new, 5,562 text-updated, 227 subchapters (209 official, 18 synthesized).
