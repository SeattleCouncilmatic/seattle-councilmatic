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

**Cross-references — bill ↔ legislation linking**
- ~~**Fix Legistar bill links.**~~ Shipped on `legislation/legistar-gateway-url`. PR #87 attempted to capture `MatterInSiteURL` from the API the way events captures `EventInSiteURL`, but the matters endpoint doesn't actually return that field — so the post-rescrape `legistar_url` was always None. Replaced with a constructed URL: `https://seattle.legistar.com/Gateway.aspx?M=L&ID=<MatterId>` (the Gateway entry-point resolves to the matter detail page; `LegislationDetail.aspx` rejects ID+GUID with "Invalid parameters!"). No re-scrape needed — `MatterId` is already in `bill.extras`.
- ~~**Link CB / Resolution references to their target bill.**~~ Shipped on `frontend/ordinance-ref-linking`. New `seattle_app/services/prose_refs.py` extracts in-prose CB/Res/Ord cites, resolves the CB and Res ones to bill slugs (Ord cites we don't store, see below), and the API returns a `{kind:num -> slug}` map alongside the prose. Frontend `BillLinkify` component scans text + looks up + renders `<Link>` for resolved cites and plain text for unresolved. Wired into `LegislationDetail` (summary / impact / key_changes desc) and `MuniCodeSection` (full_text / plain_summary). Self-references filtered out server-side. **Caveat:** "Ord. NNNNN" cites still render as plain text — the Seattle Legistar scrape gives us CB and Resolution matter records but no separate Ordinance-numbered records (the underlying CB carries the substance), so we can't resolve "Ord. 127362" to a councilmatic slug. SMC revision-history parens often cite Ord numbers; those degrade gracefully to plain text. Could later add a Legistar search-link fallback or build an Ord→CB mapping.
- ~~**Link RCW references to apps.leg.wa.gov.**~~ Shipped on `frontend/rcw-external-links` — new `RcwLinkify` component (pure client-side regex, no API change) renders `RCW 35.21.560` style cites as external links. Wired into `LegislationDetail` (`summary` / `impact_analysis` / `key_changes` description) and `MuniCodeSection` via `SectionText` (section body) + `plain_summary`. EventDetail will get it for free when transcripts ship.

**Frontend polish on legislation summary cards** *(quick)*
- **Color on the legislation summary cards.** PR #88 added the indigo CSS but it didn't apply due to a specificity tie with the later-declared `.leg-detail-section` (both single-class). Final scope on the active branch (`frontend/summary-only-indigo`, PR #91): both LLM-output cards (Plain-language summary AND Key changes) get the indigo treatment via `.leg-detail-section.leg-summary-card` (double-class wins the cascade). Bullets on Key changes go from pale `#ede9fe`/`#5b21b6` to filled `#3730a3` + white text so they pop against the indigo card.
- ~~**Make `SUMMARY` / `IMPACT` eyebrows pop.**~~ Shipped in PR #88 — bumped from gray `#6b7280` 0.75rem to indigo `#3730a3` 0.8125rem with a `#c7d2fe` bottom rule and weight 800, scoped to the LegislationDetail card. SMC page panel left as-is for now (different visual context, no complaint there).

**Councilmember data on rep detail pages**
- ~~**Bills sponsored**~~ *(quick)*. Shipped on `reps/bills-sponsored`. `get_rep_by_slug()` now includes `sponsored_bills` (top 10 by latest action) + `sponsored_bills_total`; `RepDetail` renders them via the existing `LegislationCard` and falls through to a "View all N bills sponsored by [name]" link to the legislation index sponsor filter.
- **Voting history.** The `SeattleVoteEventScraper` skeleton exists at `seattle/vote_events.py:5-9` but is stubbed to `pass`; `seattle/__init__.py:7-8` has the registration commented out. Legistar exposes `/matters/{id}/votes` per matter, which Pupa's `VoteEvent` + `VoteCount` schema already supports — implement the scraper, register it, run a backfill, then expose votes both on `RepDetail` (chronological list of "voted yes/no on CB X.Y") and on `LegislationDetail` (the existing action history could grow a roll-call section). Big lift — touches scraper, models, API, and two surfaces.
- **Committee involvements.** Today we surface `bill.extras.MatterBodyName` as the "committee" chip on bill cards but never roll it up per-rep, and we don't have committee *membership* data. Two paths to investigate: (a) Legistar `/bodies/` or `/events/` may expose committee rosters via an `EventBodyName` ↔ Person association — `seattle/events.py:171-173` already captures `EventInSiteURL`, audit whether the same response carries member lists; (b) fall back to scraping seattle.gov councilmember pages where committee assignments are listed prose-style. Once captured, render as a "Committees" section on `RepDetail` showing role (chair / member) + start/end date.
- **Tenure / "serving since".** Schema has `Membership.start_date` / `end_date` but the data isn't actually populated — `seattle/people.py:48-52` calls `add_membership(...)` without passing dates, and the Legistar people endpoint we scrape doesn't expose them. So this is a data gap, not a quick win as previously noted: requires either (a) extending the people scraper to fetch term dates from seattle.gov councilmember pages or another source, or (b) hardcoding term boundaries based on Seattle's election cycle (Districts 1/3/5/7 vs 2/4/6/At-Large stagger). Once populated, surface as "Serving since June 2024" on the rep header. Pairs with relaxing the `is_current` filter to surface former councilmembers under e.g. `/reps/former/` when we want the historical view.
- **File pointers**: `frontend/src/components/RepDetail.jsx`, `seattle_app/reps/services.py:320-365` (`_rep_row_to_dict`), `seattle_app/reps/views.py:108-118` (rep_detail), `seattle/vote_events.py` (stub), `seattle/__init__.py:7-8` (scraper registration).

~~**Accessibility audit**~~ Done. Static pass shipped findings doc (PR #104), then 17 PRs (#105–#124) cleared every priority item plus the runtime issues a Firefox Accessibility Inspector + axe DevTools sweep surfaced on the flagship pages (Home, /legislation, a bill detail, /municode, /reps, /reps/district/N). Conventions to apply on any new UI are captured in `AUDIT_FINDINGS.md` under "Conventions to keep applying" — labels, focus, contrast, headings, landmarks, live regions, document title, Leaflet maps, the two known Firefox false positives. Remaining flagship pages (an SMC section detail, a rep detail, /events + an event detail, /about, /search) weren't audited interactively but the established conventions cover what the pass would have found.

**Event transcripts → meeting summaries**
- **Capture council meeting transcripts and summarize them.** Today the events scraper pulls metadata (date, location, sponsors, agenda items, attached docs) but not the actual proceedings. Council meetings are televised on Seattle Channel and the recordings are typically captioned (probable sources: `seattlechannel.org` video archive with downloadable transcripts; YouTube auto-captions on the Seattle Council channel; possibly an SRT track on the Granicus video player Legistar embeds). Investigation needed first: (1) which surface offers the cleanest, most complete transcripts, (2) whether they're available per-event or batched, (3) licensing / rate limits. Once a source is locked, scaffold an `event_transcript_extractor` (mirrors `bill_text_extractor` shape) → `EventTranscript` model 1:1 with `Event` → `summarize_event` management command (Sonnet 4.6 + Batch API, like SMC sections). Surface as a "Plain-language summary" card on `EventDetail`, with the agenda items list still shown for reference. Past meetings only — upcoming ones don't have a transcript yet.

**Parser quality** (post-fix re-parse 2026-04-26 after `93cb885`: 7,435 sections + 1 `TitleAppendix` / 28 `ParseValidationIssue` rows / 234 official + 1 synthesized subchapter / 8 declared-but-empty)
- **Last 1 missing section** (`23.48.235`). The PDF lacks a clean section heading: section number lives in the running header (`'SEATTLEMIXED 23.48.235'`) and the title `'Upper-Level Setbacks'` appears on its own line after a figure caption (`'Map A for 23.48.235'`). Probably PDF source data issue — defer unless we find a generalizable fix. (`23.50A.160`, `23.76.067`, `25.24.030` all recovered this session — see Done. `12A.14.160` confirmed nonexistent: not in PDF, TOC jumps from `.150` to `.175`, no `ParseValidationIssue` row for it, dropped from the missing list. `5.48.050` recovered via PR #28's `Ord. + §` boundary rule.)

## Open threads

Lower-priority backlog — fix when you're already in the area, not worth scheduling.

- **Body-text word merging on tight-kerning pages.** `pdfplumber.extract_words(x_tolerance=2)` cleanly extracts section *titles* (only 1 title across the corpus matches `[a-z][A-Z]` merges), but body text in many sections has runs of merged words like `throughOrdinance`, `InaccordancewithRCW35.21.560`, `City'slegislative`. Worst offenders concentrate in Title 21 (utilities, esp. chapter 21.49) with sections hitting 50–117 lowercase-uppercase merge points; total ~1,500 sections across all major titles have at least one camelCase-shaped merge (and lowercase-lowercase merges like "ofthe" go uncounted, so the real number is higher). Hypothesis: the body-text regions of certain pages have tighter kerning than `x_tolerance=2` can bridge. Likely fix path: bump `x_tolerance` (try 3 then 4) on a branch, re-parse a sample range, validate no regressions in titles or other sections; ship if clean. Re-summarization needed for affected sections after a parse fix because the LLM summaries are derived from the merged text. Defer until we have a maintenance window — the merges hurt readability but don't break navigation, and the LLM summaries paper over much of the issue.
- **Master "Table A for 23.47A.004" not extracted.** pdfplumber's default `lines` strategy doesn't detect this table — likely renders without strong drawn borders or spans multiple PDF pages (or both). 84 other tables across the SMC ARE captured by lines strategy (see PR #59), so the table-aware path works for the common case; this is the master use-permissions table that's referenced by many LUC sections. Tried `text` strategy as a fallback once — it fired on prose pages and broke section detection (4,296 emitted vs 8,834 expected, plus a Subchapter `name > 200` crash from polluted body lines). The strict guards (≥3 rows, ≥3 cols, mean cell length < 30) weren't tight enough against SMC's deeply-indented enumeration body pages, which text-strategy reads as wide tables of short cells. Future approaches worth considering: (a) gate text-strategy on a "Table" keyword on the page, (b) require ≥5 rows AND ≥4 cols AND mean cell length < 15 in strict mode, (c) only run text-strategy on pages whose lines-strategy `find_tables` returns *near*-tables (some lines/curves but no closed rect), (d) add a defensive name-length truncate on Subchapter / `_resolve_subchapter` so a polluted line never crashes the whole parse.

---

## Conventions

**Branch names:** `<area>/<short-desc>` — e.g. `parser/subchapter-toc`, `frontend/vite-cutover`, `backfill/landmark-types`.

**Before switching branches:** WIP commit (`wip: <short-state>`) and push so nothing is orphaned in a detached working tree.

**Branch follow-ups from `main`, not from in-flight branches.** Stack only when the new work genuinely depends on the prior branch's code. Stacking on an unmerged branch costs a rebase later — root cause of the WORK_LOG conflict on `frontend/spa-notfound`.

**Include the Done-move in the same PR that ships the work.** Add the workstream's entry under `## Done` in the same commit. Avoids the "stale section after merge" tax we kept hitting.

**Pre-flight at session start:** `git fetch && git log main..origin/main` to catch divergence between local and remote `main` before doing anything else. We lost time to a 16-commit divergence in 2026-04 that this would have caught in one command.

---

## Done

### Reps — scrape committee memberships → OCD Organization + Membership — committed 2026-05-02

Each councilmember's `/council/members/<slug>/committees-and-calendar` page lists 4-6 committee assignments with role (Chair / Vice-Chair / Member). The pupa scraper now fetches that page during the people scrape, parses the committees ul, and yields one OCD `Organization` per unique committee plus one `Membership` per (person, committee) with the role.

`extract_committee_assignments(html_str)` is the parser. The scrape collects all committees in a first pass, dedupes by URL slug (committee names vary in punctuation across reps' pages — `Seattle Center` vs `Seattle-Center` — so the slug is the stable identifier), then yields the Organizations followed by the Persons with their committee memberships. Canonical name = first-seen display text for that slug.

API: `_rep_row_to_dict` now returns a `committees` array of `{name, role, organization_id, source_url}` sorted Chair → Vice-Chair → Member then alphabetically. Frontend: new `Committees` section between External Links and Bills sponsored, with role pills (filled navy / outlined navy / light gray) and committee names linked out to seattle.gov.

Live data: 9 unique committees, 44 (person, committee) memberships across the 9 current councilmembers. Dropped naturally for former members — `/committees-and-calendar` 404s for `sara-nelson` and `mark-solomon` so the existing redirect-skip pattern protects us. One known data quirk: Rinck's page has a copy-paste href bug (her Libraries entry's href points at Transportation), so she shows two memberships to Transportation — when seattle.gov fixes their page, our next scrape clears it up.

### Events — clean up 91 stale midnight Event duplicates — committed 2026-05-02

Pre-PR-#34 (committed 2026-04-28) the events scraper read only Legistar's `EventDate` field, which always carries midnight; the wall-clock time lives in a separate `EventTime` field. Every event scraped before that fix landed at midnight Pacific (07:00 UTC during PDT, 08:00 UTC during PST). When the fix shipped the next scrape created *new* event rows at the correct time — pupa upserts on (name + start_date), so a different start_date yielded a new row rather than updating the existing one. Result was 91 (name, date) groups in the DB with both a stale midnight row and a corrected row, double-displaying in `/events/`.

Migration `0022` deletes the stale midnight rows in groups that also contain a non-midnight sibling — that sibling guarantees we know the real meeting time, so the deletion is non-destructive. (Verified pre-flight: 91 candidates, 0 unsafe groups where every sibling is midnight.) Uses Django ORM `.delete()` so OCD's model-level `on_delete=CASCADE` fires for the related EventAgendaItem / Document / Link / Media / Participant / Source rows plus the downstream `councilmatic_core.Event` row — the DB-level FKs are `NO ACTION`, so a raw-SQL `DELETE` on `opencivicdata_event` would have errored. Total events 1230 → 1139.

### Scrapers — retry-with-backoff on Legistar HTTP — committed 2026-05-02

Cron logs show ~1-2 `RemoteDisconnected` hits per daily run from Legistar's API. Most are inside per-record fetches (sponsors / attachments / histories for a single bill, agenda items for a single event) — the scraper logged a warning, returned empty, and the run continued with that record silently incomplete. **One run today (2026-05-02) hit the bulk events list endpoint instead** — `_fetch_events` returned `[]` on the disconnect, pupa raised `ScrapeError: no objects returned from SeattleEventScraper scrape`, and the entire daily sync (events + bills + sync_councilmatic) failed. Monday's Council Briefing didn't show up in the UI as a result.

New `seattle/_http.py:request_with_retry` wraps `requests.get` with exponential backoff (1s, 2s, 4s — 3 attempts default) and re-raises `RequestException` on final failure. Wired into all five fetch points: `_fetch_events`, `_fetch_event_items`, `_fetch_packet_url` in events.py; `fetch_bills`, `fetch_matter_detail` in bills.py.

Behavior change at the edges: per-record helpers still swallow + log on final failure (a missing sponsor list on one bill is preferable to dropping the bill), but `_fetch_events` no longer swallows — if all retries fail we want the run to die visibly with the network exception, not silently produce no events. Today's failure mode of "drift in for a day with stale data and nobody noticed" is the worse outcome.

### Reps — scrape phone, fax, addresses from per-member contact tile — committed 2026-05-02

The per-member seattle.gov detail pages each carry a Contact Us tile with phone, fax, email, office address, and mailing address. The pupa scraper only emitted a guessed `firstname.lastname@seattle.gov` email before. Now it also fetches the per-member page during scrape and pulls the rest of the tile into `core.PersonContactDetail` rows. Two address rows per person (`note='Office'` / `note='Mailing'`), one phone (`type='voice'`), one fax (`type='fax'`), and the canonical-capitalization email (which matters for `Alexis Mercedes Rinck` since the real mailbox is `AlexisMercedes.Rinck@seattle.gov`, not the guessed `alexis.mercedes.rinck@seattle.gov`).

`extract_contact_details(html_str)` is the shared parser, used both inside `SeattlePersonScraper.scrape()` and from the new `backfill_council_contacts` management command that idempotently populates the existing 11 Person rows without requiring a full pupa rerun. Addresses are stored multi-line with `\n` separators (line breaks at `<br/>` in the source), and the frontend renders them via `white-space: pre-line` on `.rep-detail-contact-address`.

`reps/services.py:_rep_row_to_dict` extends the contact-details loop to expose `fax`, `office_address`, and `mailing_address`. `RepDetail.jsx` adds Phone (already wired but never populated), Fax (display-only), Office address, and Mailing address rows using lucide `Printer` and `MapPin` icons.

Both scraper and backfill use `requests.get(..., allow_redirects=False)` and skip non-200 responses — seattle.gov 301s former-member URLs to their successor's page (`sara-nelson` → Dionne Foster, `mark-solomon` → Eddie Lin), which would otherwise attribute the successor's contact info to the former member's record. Sara Nelson and Mark Solomon keep the old guessed-email contact only.

### Reps — switch profile link to per-member detail page — committed 2026-05-02

Was linking to `https://www.seattle.gov/council/members#DeboraJuarez` (anchor on the index page). Now links to `https://www.seattle.gov/council/members/debora-juarez` — the per-member detail page that carries about/committees/staff/blog content we'll pull from in follow-on work.

`seattle/people.py` gets a `profile_slug(name)` helper (lowercase + spaces→hyphens) plus a small `PROFILE_SLUG_OVERRIDES` dict for cases where seattle.gov uses a preferred name on the URL — currently just `Robert Kettle → bob-kettle`. Migration `0021_update_council_profile_urls` walks existing `core.PersonLink` rows with `note='City Council profile'` and rewrites the URL using the same rule (no re-scrape required). Verified all 11 stored profiles (9 current + Sara Nelson + Mark Solomon + Debora Juarez) update cleanly.

Caveat: seattle.gov silently redirects former-member URLs to their successor (e.g. `sara-nelson` → Dionne Foster's page, `mark-solomon` → Eddie Lin's page) rather than serving an archived profile. Debora Juarez still has her own archived page. Acceptable for now — the link works and lands on the seat's current holder, which is at least informative.

### Frontend — NavBar reorder — committed 2026-05-02

Tiny ergonomic reorder. New order: `Home · City Council · Legislation · Events · Municode · About`. Surfaces the human-facing pages (council members, bills, meetings) before the reference/utility ones (municipal code, about). About moves to the tail since it's a one-time read, not a recurring destination. No behavior changes; `NAV_ITEMS` array reorder in `NavBar.jsx` only.

### LLM — render legislation summaries in API + frontend (Stage 3 of bills pipeline) — committed 2026-04-30
Final stage of the bills LLM pipeline — surfaces the summaries to users.

**API** — `/api/legislation/<slug>/` gets a new `llm_summary` block. Contains `summary` (prose), `impact_analysis` (prose), `key_changes` (the JSON list with title/description/affected_section per item), `affected_sections` (resolved M2M list of `{section_number, title}` for resolvable references), `model_version`, `generated_at`, `summary_batch_id`. Returns `null` when the bill hasn't been summarized yet, so the frontend can render the page either way.

**Frontend** — two-card layout above the existing sidebar/timeline grid in `LegislationDetail`:
- Card 1, "Plain-language summary": holds Summary + Impact prose, distinguished by small uppercase `SUMMARY` / `IMPACT` eyebrows. Both prose blocks split on `\n\n` and emit one `<p>` per chunk (same treatment as the SMC summary panel).
- Card 2, "Key changes": numbered list (`<ol>` with CSS counter) where each item has a title, description, and a "Affected: SMC X.Y.Z →" footer. The footer is a real `<Link>` when the section number resolves to a `MunicipalCodeSection` row (we use the API's `affected_sections` list as the validation set); for unresolved references (chapters like `23.32`, deprecated sections, typos), it falls back to plain monospace text in muted color.

Container `max-width` bumped from 1100px → 80rem to match the SMC pattern. Existing `.leg-detail-section` card chrome is reused for the new cards via a shared `.leg-summary-card` marker class. Bills without an `llm_summary` (operational bills the LLM correctly identified as code-touch-free, or anything not yet processed by the batch) skip the cards entirely and render the original layout.

### LLM — `summarize_legislation` command (Stage 2 of bills pipeline) — committed 2026-04-30
Reads `BillText.text` (populated by Stage 1's `extract_bill_text`), submits each bill to Sonnet 4.6 via the Anthropic Message Batches API, and persists structured results to the existing `LegislationSummary` model. Two-phase like `summarize_smc_sections`: first invocation submits, subsequent invocations poll + process. State at `data/summarize_legislation_state.json` (gitignored).

**Schema**: new `LegislationSummary.summary_batch_id` (CharField max 64) — parity with `MunicipalCodeSection.summary_batch_id` from PR #73. Migration `0019_legislationsummary_summary_batch_id`.

**Per-bill request**: cached `LEGISLATION_SYSTEM_PROMPT` (`cache_control: ephemeral`) + structured JSON output via `output_config.format.json_schema` against the existing `LEGISLATION_OUTPUT_SCHEMA` (summary, impact_analysis, key_changes[]). Explicit thinking budget `{"type": "enabled", "budget_tokens": 8192}` with `max_tokens=16384` — same lesson learned in PR #70 about adaptive thinking starving output. Bill identifiers go through space↔underscore encoding for the `custom_id` field (Anthropic's `^[a-zA-Z0-9_-]{1,64}$` doesn't allow spaces in `"CB 121177"` style identifiers).

**Input cap**: 600k chars per bill, tail-truncated. Opus's 200k-token context fits ~800k chars but we need room for system prompt + thinking + output. p95 of `BillText.text` is 192k chars, so the cap only bites on the very largest bills (e.g., CB 120993 at 871k chars) — and `BillText` concatenates the staff Summary first, so truncating the tail keeps the most useful content.

**Idempotency + affected_sections**: bills with an existing `LegislationSummary` row are skipped unless `--force`. After parsing the LLM's structured response, `key_changes[].affected_section` strings are resolved to `MunicipalCodeSection` rows via `section_number` lookup and saved to the M2M; unmatched section numbers (typos, deprecated sections) are silently dropped from the M2M but remain in the JSON for the audit trail.

**Model selection**: `CLAUDE_LEGISLATION_MODEL` default flipped from `claude-opus-4-7` → `claude-sonnet-4-6`. The original "Opus for legislation" decision was made before we'd tested anything; with the structured JSON output config enforcing format and the input being mostly staff-prepared plain-language summaries, Sonnet is sufficient and ~5x cheaper. New `--model` CLI flag for ad-hoc A/B testing (e.g. `--model claude-opus-4-7 --limit 5` to compare on a smoke batch).

**CLI**: `--limit N`, `--force`, `--dry-run`, `--bill <identifier>`, `--model`, `--state-file`.

**Cost estimate** (with current size distribution: avg 40k chars, p95 192k chars, max 871k chars per bill): **~$17 total** via Sonnet 4.6 + Batch API + cached system prompt for the full 381 bills (~$85 if escalated to Opus).

### LLM — bill text extractor (Stage 1 of bills pipeline) — committed 2026-04-29
First piece of the bills LLM pipeline. The OCD/pupa scraper only stores attachment URLs (not text), so this stage adds the download + extract layer that the bills summarizer (Stage 2) will read from.

**`seattle_app/services/bill_text_extractor.py`** — pure helper. `extract_text(url, media_type)` downloads and returns plain text; PDF via `pdfplumber.extract_text()`, .docx via `python-docx` (paragraphs + tables in document order). Legacy `.doc` binary is logged + skipped. `combine_bill_documents(documents)` is the picker: categorizes each attachment by its note (`summary` / `signed` / `affidavit` / `other`), extracts the staff summary and signed canonical text, concatenates with `[STAFF SUMMARY AND FISCAL NOTE — …]` and `[SIGNED CANONICAL TEXT — …]` section markers so the LLM can tell staff framing apart from canonical text.

**`seattle_app.BillText` model** — 1:1 with `councilmatic_core.Bill`. Fields: `text` (concatenated extraction), `source_documents` (per-document audit JSON: note/url/media_type/category/char_count/error), `extracted_at` / `last_regenerated`. Migration `0018_billtext`.

**`extract_bill_text` management command** — iterates bills missing `BillText`, prefetches `documents__links`, hands them to the extractor, persists. Idempotent on `BillText` existence; `--force` to re-extract; `--bill <identifier>` for one-off; `--limit N` for smoke runs; `--include-other` to opt non-summary/non-signed docs into the extraction (off by default to keep noise out).

Why staged separately from the summarizer: extractor quality is the riskier unknown. Iterating on the extractor (table-aware, header-aware, OCR fallback if needed) shouldn't force re-running summaries; iterating on prompts shouldn't force re-downloading PDFs. `BillText` is the cache between them.

### Frontend — render SMC section summaries in a wide 2-column layout — committed 2026-04-29
First user-visible piece of the LLM-summaries feature. `MuniCodeSection.jsx` now displays the `plain_summary` (already exposed by the API) alongside the full text. At ≥1024px viewports the page splits into a 2-column grid (`minmax(20rem, 1fr)` summary / `minmax(0, 1.4fr)` body); below that, the summary stacks above the body. Sections that don't yet have a summary fall back to the body filling the row — no phantom empty column.

Layout: container `max-width` bumped from 56rem → 80rem so the page actually uses the screen on desktop. Other municode detail pages (Title, Chapter, Appendix) get the wider container too — listings still look right because they're flex rows that adapt to width.

Summary rendering: split on `\n\n` and emit one `<p class="smc-summary-body">` per chunk so multi-paragraph summaries don't render as a wall of text. The model-version footer gets a top border to visually separate from the body.

### LLM — bulk `summarize_smc_sections` command (Batch API + cached few-shots) — committed 2026-04-29
Single management command with two phases sharing one state file (`data/summarize_smc_state.json`, gitignored — batch IDs are per-environment).

Phase 1 — submit. First invocation gathers `MunicipalCodeSection` rows where `plain_summary == ""` (all of them on a fresh DB; skipped on re-run unless `--force`), composes the system prompt as `SECTION_SYSTEM_PROMPT + 5 few-shot examples` (~17k chars / ~4-5k tokens), marks it `cache_control: ephemeral`, and submits one batch via `client.messages.batches.create(requests=[…])`. Each request carries its `section_number` as `custom_id` so results can be matched back. Persists batch ID + submitted-at + section count.

Phase 2 — poll + process. Subsequent invocations call `messages.batches.retrieve(batch_id)`, print the request-counts breakdown, and exit if `processing_status != "ended"`. Once ended, `messages.batches.results` streams JSONL; succeeded results write `plain_summary`, `summary_model`, `summary_generated_at` (single `update_fields` save per row); errors are captured to state. State gets `processed: True` after, so a follow-up run picks up any sections still missing summaries and submits a fresh batch.

CLI: `--limit N` for smoke runs, `--force` to re-summarize, `--dry-run` to preview without API calls, `--few-shots`/`--state-file` to override paths.

Sized for the SMC's ~8,800 sections in a single batch (well under Anthropic's 100k-request limit). Cost target: ~$60 for the bulk run with Sonnet 4.6 + cached system prompt + Batch API discount; cache writes amortize across the batch's 5-minute windows.

### LLM — lock canonical few-shot examples for SMC section summaries — committed 2026-04-29
Curated 5 final few-shot examples saved to `data/few_shot_section_summaries.json` (no timestamp; the bulk Sonnet command reads this path). Each example covers a distinct archetype: definitions/admin (`8.37.020`), penalty/enforcement (`22.170.170`), LUC use restrictions (`23.50.012`), permit-procedural (`23.76.012`), long substantive policy (`25.05.675`).

Curation took four Opus iterations against the section system prompt:

1. **v1** (PR #60 default prompt): all 5 outputs were 1.5k–3k chars vs the "1-3 short paragraphs" target; used markdown headers + bullets + bold the frontend isn't set up to render; repeated the section title in `##` headings; `25.05.675` was truncated mid-bullet at the 1024 `max_tokens` default.
2. **v2** (PR #61): tightened length to "150–300 words / hard cap 400 words", forbade markdown formatting + title repetition, locked second-person voice, bumped bootstrap `max_tokens` to 1500. Fixed the formatting axes; the four substantive sections were locked-in. But the strict admin rule produced a 504-char dead-end summary for `8.37.020` ("this is a definitions section, look it up"), useless for navigation.
3. **v3** (PR #62): relaxed admin rule to "one or two short sentences". Opus took the relaxation as license to organize terms into 6 functional categories — more useful than v2 but technically violated the "1-2 sentences" wording.
4. **v4** (PR #63): aligned the prompt to ask directly for the categorize-and-map shape ("group what the section covers into a few functional categories and name the terms or topics within each, but do not explain individual term meanings"). Result: 2,135-char categorized summary that gives readers a navigation map without explaining individual terms.

Locked-in summary lengths: 2,135 / 2,152 / 2,310 / 2,375 / 2,359 chars. All within target, no markdown, plain prose with `\n\n` paragraph breaks (frontend should split on `\n\n` and emit `<p>` per chunk).

### LLM — bootstrap command for few-shot section summary calibration — committed 2026-04-28
First piece of the LLM-summaries pipeline. `bootstrap_section_summaries` calls Opus on 5 curated SMC sections (one per archetype: definitions, long substantive policy, penalty/enforcement, permit-procedural, LUC use restrictions) and writes the results to a timestamped JSON in `data/`. Outputs are not written to the DB — they're calibration artifacts that exist to teach Sonnet via few-shot prompting on the bulk run.

The 5 curated picks: `8.37.020` (Definitions), `25.05.675` (Specific environmental policies — longest in corpus at 52k chars), `22.170.170` (Violations and Penalties), `23.76.012` (Notice of application), `23.50.012` (Permitted and prohibited uses). Excludes `23.47A.004` (master Table A is the known-gap from the open thread; full text incomplete) and several near-duplicate samples.

Settings: new `CLAUDE_BOOTSTRAP_MODEL` (defaults to `claude-opus-4-7`), and `CLAUDE_CODE_SECTION_MODEL` default flipped from `claude-haiku-4-5` to `claude-sonnet-4-6` after planning concluded Haiku was too inconsistent for the legal-summary task. Timestamped iteration outputs in `data/few_shot_section_summaries_*.json` are gitignored; the curated final at `data/few_shot_section_summaries.json` (no timestamp) gets checked in once locked.

### Parser — table-aware extraction for permission tables in LUC sections — committed 2026-04-28
Closes the long-standing "permission tables come out as bare-code soup" bug for sections like `23.47A.004` and `23.54.015`. pdfplumber's word-level reader splits each page at `mid_x = page.width / 2`; a permission table that spans both columns gets its cell values randomly assigned to left/right based on column-relative position, producing strings like `X X X CCU CCU` / `P P P P P` with no row labels attached.

`_extract_page_lines` now:

1. Calls `page.find_tables()` and serializes each detected table to markdown rows (header + `---` divider + body rows). Single-row or single-column "tables" — usually layout-grid false positives — are rejected via `len(rows) >= 2 AND width >= 2`. Cell content is flattened to single line; `|` is escaped.
2. Excludes any word whose center falls inside a table bbox from the column-aware reader, so the same cell content doesn't appear twice in the output.
3. Appends each table block (preceded by a blank separator) at the end of the page's body lines after the existing prose folds.

Position is page-accurate, not intra-page-accurate — a table appears at the section's tail rather than mid-section if prose surrounds it. For typical LUC sections (section heading + one big Table A) this works well; for the rare sandwich case the data is preserved but slightly out of order. Markdown chosen over HTML so plain-text body dumps stay readable; FTS still tokenizes cell values as searchable text. `ts_headline` snippets that land in a table will look pipe-heavy — refine later if it bothers users. Re-parse required.

### Parser — split embedded subchapter dividers out of dense TOC section entries — committed 2026-04-28
Fixes the chapter-25.10 family of TOCs where a section number and the next subchapter divider share one line — e.g. `25.10.110 Applicability. Subchapter II. Definitions`. SECTION_RE consumed the entire line, so `Subchapter II. Definitions` got glued onto the section title and the divider was missed by the TOC scanner; the result was Subchapter II's name dropped and its declared sections wrongly attributed to Subchapter I.

New module-level `EMBEDDED_SUBCHAPTER_IN_TITLE_RE` matches `\.\s+(Subchapter <Roman>[. <name>])$` — the leading `.` and required whitespace are the false-positive guard against in-prose mentions like "Reference to Subchapter X for further info" (no period before, no match). When the SECTION_RE handler in `_TocScanner.observe` finds an embedded match, it records the declared section number as before, then finalizes the current draft and starts a new one for the embedded subchapter. State advances to `_STATE_IN_SUBCHAPTER_SECTIONS` if the embedded form has a name, or `_STATE_IN_SUBCHAPTER_NAME` if not. Re-parse required.

### Parser — guard the inline soft-hyphen title fold against column-split garbage — committed 2026-04-28
Fixes `8.38.010 Short title "CannaThis Chapter 8.38 shall constitute the…` and any similar section where pdfplumber's column-aware reader drops the wrong column's text into the next-line slot. The standalone `_fold_soft_hyphens` already had the right guards (lowercase first char, not a heading); the inline fold-during-emit at the section-match site was blindly concatenating `lines[i + 1]`. Mirror the same guards there: only fold when the next line plausibly continues the broken word. If the fold doesn't apply, drop the trailing `-` rather than emitting a title that ends with a soft hyphen.

For the visible bug case `8.38.010` becomes `Short title "Canna` (truncated but no longer absurd) instead of fold-merging body prose. Re-parse required to apply the fix to existing rows.

### Frontend — NavBar mobile hamburger — committed 2026-04-28
Closes the deferred-from-PR-#33 mobile-nav item. Below 768px the navbar collapses to a hamburger toggle on the right; tapping it drops a vertical list panel below the header, anchored to `.header` (which is `position: sticky` and counts as a positioning ancestor). The panel uses `position: absolute; top: 100%; left/right: 0` to span the full header width.

State + dismissal: `useState` for open/closed; closes on path change (covers tap-an-item via `useLocation` watcher) and on Escape (keydown listener registered only while open). No outside-click handler — path-change covers the common dismissal flow and keeps the implementation small. Hamburger button uses `aria-expanded` / `aria-controls` and a Menu↔X icon swap from lucide-react (already a dep). Desktop styling unchanged: hamburger hidden via `display: none`, items render inline.

### Events — capture `EventTime` in pupa scraper + restore frontend time display — committed 2026-04-28
Closes the long-standing midnight-everywhere bug filed during the events-filter PR. Legistar splits a meeting timestamp across two fields: `EventDate` always carries midnight, with the wall-clock time in `EventTime` as a 12-hour string like `"9:30 AM"`. The scraper was reading only `EventDate`, so every row in the DB had `start_date` set to midnight-Pacific (`07:00:00+00:00` or `08:00:00+00:00` depending on DST).

**Backend:** `SeattleEventScraper._parse_event` now strips and parses `EventTime` with `%I:%M %p`, then composes the result onto the date via `event_date.replace(hour=…, minute=…)` before localizing to Pacific. Defensive: missing or unparseable `EventTime` falls back to midnight (current behavior) and logs a warning rather than dropping the event — verified `12:00 AM`, `12:00 PM`, mixed-case, and trailing-whitespace inputs all parse; `"9:30"` (missing `AM/PM`) raises and is caught.

**Frontend:** `EventCard.formatEventDate` and `EventDetail.formatDateTime` swapped from `toLocaleDateString` to `toLocaleString` with `hour: 'numeric'` + `minute: '2-digit'` (and `timeZoneName: 'short'` on the detail page only — too noisy on the card list). Re-scrape will run on the next scheduled scrape (every few hours); existing rows still display midnight until then.

### Frontend — relabel "This Week" → "Home", "My Council Members" → "City Council"; rename `meeting-*`/`mtg-*` CSS classes — committed 2026-04-28
Two threads bundled into one PR.

**Label rename.** `This Week` was the homepage's section heading; using it as a NavBar/breadcrumb label conflated "this week's content" with "the homepage" and got stale once the homepage grew beyond a single weekly view. Renamed to `Home` everywhere it appeared as a navigational label (NavBar landed in PR #53, this PR sweeps the breadcrumbs across every index/detail page, the About copy, and `NotFound`'s default-variant link). The actual homepage section heading still reads "This Week" inside `ThisWeek.jsx` — that's content, not nav. Also renamed `My Council Members` → `City Council` in NavBar + breadcrumbs (RepsIndex, RepDetail, RepDistrict) + About feature list — tighter, less first-person, fits in narrow NavBar widths better.

**CSS class rename.** Closes the last of the index-polish leftovers: vestige `.meeting-*` / `.mtg-*` class names from the pre-PR-31 MeetingCard/MeetingDetail era now align with the rest of the events surface under a single `.evt-*` prefix. EventCard.css's mixed `.meeting-card-*` + `.event-card-*` + `.event-type-*` collapsed to `.evt-card-*` + `.evt-type-chip*`; EventDetail.css's `.mtg-detail-*` / `.mtg-doc-*` / `.mtg-att-*` / `.mtg-agenda-*` / `.meeting-badge*` all → `.evt-*`. `.matter-chip*` left as-is (not a vestige). Verified the built CSS surfaces 40+ `.evt-*` classes and zero `.meeting-*` or `.mtg-*` survivors.

### Frontend — NavBar trim (drop dead hash stubs) — committed 2026-04-28
Closes the NavBar piece of the index-polish leftovers. NavBar previously carried three hash-anchor stubs (`#this-week`, `#how-it-works`, `#glossary`) pointing at homepage sections that didn't exist (or, in the case of `#this-week`, only worked on the homepage and silently no-op'd from any other route since `Header` renders NavBar everywhere).

Changes:

- `This Week` → renamed `Home`, `to: '/'` (now works as a real cross-page link from any route).
- `How It Works` → removed; the existing `About` item already covers that content.
- `Glossary` → removed entirely. Re-introduce as `/glossary` if/when we decide to author the content.

Final NavBar order: Home · About · Events · Legislation · Municode · My Council Members. All six are now real `Link to=…`s — no more silent-failing hash anchors. `isActive` simplified accordingly with a small special-case for `to: '/'` (otherwise the generic `pathname.startsWith(to + '/')` would mark Home active on every page).

### Legislation — group sponsor dropdown by current vs former council — committed 2026-04-28
Small follow-up to PR #48. The flat sponsor dropdown surfaced 14 names alphabetically, mixing current and former council members with no visual cue. Now the `<select>` splits into two `<optgroup>`s — "Current council" (9) and "Former members" (5) — keyed off `councilmatic_core_person.is_current`.

API: `_list_legislation_sponsors` reshaped from `list[str]` → `dict[str, list[str]]` with `current` / `former` keys. New `_current_council_member_names()` helper drops to raw SQL because `is_current` was added by a raw `ALTER` (see migration `0001_add_is_current_to_person`) and isn't on the `Person` ORM model. Filter validation accepts names from either bucket via the union; everything else (filtering, distinct, etc.) unchanged.

Frontend: `sponsorValues` state default flipped to `{ current: [], former: [] }`; render uses two `<optgroup>` blocks with the native HTML divider. Empty buckets are guarded so the optgroup labels don't render against empty option lists.

Verified: filtering by Dan Strauss (current) returns 173 bills, Sara Nelson (former) returns 49; bogus name still rejected.

### Legislation — sponsor filter — committed 2026-04-28
Fourth of the index-polish bundle. `/legislation/` gets a sponsor dropdown alongside the existing status filter — 14 distinct council member names sourced from `BillSponsorship.name`, sorted alphabetically. Legistar's `' No Sponsor Required'` placeholder is filtered out; everyone else surfaces.

API: new `sponsor` query param, exposed `sponsor_values` in the response. New `_list_legislation_sponsors` helper computes the canonical list once per request (small — 15 distinct rows in the table). The filter joins through `sponsorships__name__iexact` with a `.distinct()` guard against the join-duplicate case (a bill can have multiple sponsorship rows pointing at the same person).

Notable footgun caught: `BillSponsorship.entity_name` is a Python property, not a DB column — Django's `values_list('sponsorships__entity_name')` errors with "Unsupported lookup 'entity_name' for UUIDField." The actual DB column is `name`, which equals `entity_name` for person-typed sponsors (which is everyone in our data). Documented in the helper's docstring.

Frontend: parallel state, dropdown, change handler. URL-synced like the other filters.

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
