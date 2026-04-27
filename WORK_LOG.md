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

**Frontend**
- **Meeting agenda items (WIP).** Pick up the work in worktree `claude/zealous-tharp` at `.claude/worktrees/zealous-tharp`, commit `baa719c`. Touches `seattle/events.py` (uncomment + implement `_add_agenda_items`, scrape `hypAgendaPacket` from Legistar HTML), `seattle_app/api_views.py` (return `agenda_items`, `agenda_file_url`, `packet_url`, `minutes_file_url`, `minutes_status`), `frontend/src/components/MeetingDetail.jsx` (~93 LoC of new components: `MatterChip`, `DocIcon`, `AgendaDocButtons`, `AgendaItemRow`). When ready: branch from `main`, cherry-pick `baa719c`, open PR.

**SPA index/search pages** (each likely its own PR; specifics TBD when we pick them up)
- `/legislation/` — search and browse all legislation. `ThisWeek` only shows recent; needs an API search endpoint (or extend `/api/legislation/recent/` with query params) plus a list/filter UI. After shipping, update the `NotFound` `legislation` variant link from `/` to `/legislation/`.
- `/events/` — search and browse all council meetings. Same shape as the legislation index. After shipping, update the `NotFound` `meeting` variant link from `/` to `/events/`.
- `/municode/` — search and browse the Seattle Municipal Code. First user-facing surface for the `MunicipalCodeSection` rows the parser populates. Big open questions: search vs hierarchical browse (Title → Chapter → Section), full-text vs metadata filters, how to render section text. Natural place to surface section-level LLM summaries when those wire up.

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
