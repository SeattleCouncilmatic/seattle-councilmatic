# External Communications Plan

## Context

The Seattle Councilmatic site has two distinct outbound-communication needs
that share infrastructure but have very different operational shapes:

1. **Ops alerting & liveness** — somebody needs to know when a cron job fails
   silently. Last night's run of `summarize_legislation` errored all 19
   candidate bills with no notification; the failure surfaced only because a
   human happened to check CB 121215 on prod. The fix (PR #198) recovered the
   per-request error context, but the alerting gap remains.
2. **Personalized digest emails** — opt-in weekly (and optionally daily)
   updates filtered to issue areas, councilmembers, district, and individual
   bills.

These need to be planned together because the digest pipeline pulls in most
of the infrastructure (Postmark account, verified sending domain, SPF/DKIM/
DMARC, redaction filter, `postmarker` SDK, webhook handling) that ops
alerting also wants. Treating them as one plan avoids provisioning the same
account twice and lets the ops layer ride on infrastructure the digest plan
already needs.

That said, **Phase 1 is intentionally independent**: it ships as its own PR
and stands on its own merits regardless of whether the digest project ever
moves forward. The Healthchecks layer that catches "the cron job is dead"
lives outside our infrastructure on purpose — its independence is what
makes it useful — so it has no Postmark dependency and no digest-feature
dependency.

The user has explicitly asked the plan to address (a) security around
storing emails, (b) costs of bulk email + LLM, and (c) legal/compliance
implications. These are called out in dedicated sections below alongside
the implementation steps, with Phase 1's tiny security/cost/legal surface
called out separately at the top of each.

## Decisions already made

### Ops alerting layer (Phase 1)

- **Liveness signal**: Healthchecks.io (free tier covers 20 checks; we will
  use ~5). Cron wrappers ping `/start`, then `/<uuid>` on clean exit or
  `/<uuid>/fail` on non-zero exit. The point of Healthchecks specifically
  is that the alerts are delivered by infrastructure outside our box, so
  "the whole machine died" is a case Healthchecks can still report on.
- **Rich error reporting** (added in Phase 3, when Postmark exists):
  `mail_admins()` from each batch command's `_process_results` when
  `error_count > 0`, with a body listing the per-request error strings
  produced by `format_batch_error()` (added in PR #198).
- **Admin list storage**: Django `settings.ADMINS` — *not* a DB-backed
  table. Reasoning: ops alerts must work when the DB is down (the case
  you most need them); standard Django pattern; tools like Wagtail and
  `AdminEmailHandler` already plug into `settings.ADMINS` directly;
  editing 1-3 addresses yearly does not justify a Django admin UI for
  rotation. If granular per-admin subscriptions ever become necessary
  (e.g., one admin wants only digest alerts), a thin DB-backed wrapper
  can be added later without breaking the simple case.
- **Logging handler scope** (Phase 3): explicit `mail_admins()` calls
  only. Do *not* wire `django.utils.log.AdminEmailHandler` to the root
  logger or to the default `django` logger. Rationale: Healthchecks
  already covers the "something's broken" signal at the infrastructure
  level; broad handler wiring risks inbox flooding during a flaky
  deploy or when a third-party library spams at ERROR level. Narrow
  wiring keeps email volume predictable — one email per intentional,
  explicit failure point. Django's default `LOGGING` dict wires
  `AdminEmailHandler` to the `django` logger at ERROR when
  `DEBUG=False`; we replace it in Phase 3 with a project `LOGGING`
  dict that excludes the handler. Revisit only if we find a failure
  mode that isn't already covered by Healthchecks + per-command
  `mail_admins()`.
- **Notification channels** (Phase 1): email only via the Healthchecks
  dashboard.
- **Notification channels** (later): Slack opt-in via the Healthchecks
  dashboard (no code change). Future: Claude-on-Slack diagnose-and-PR
  loop is plausible (the MCP server list already includes Slack tools
  and `github.create_pull_request`), but that is a separate plan doc.

### Outbound email + digests layer (Phases 2-7)

Carried over from the previous personalized-digests plan, unchanged
except for renumbering:

- **Personalization dimensions**: issue tags, councilmembers, council
  district, individual bills.
- **Auth**: email-only, double opt-in. No passwords. Magic-link tokens.
- **Cadence**: opt-in weekly (default) and opt-in daily-when-there's-news.
- **LLM at send time (v1 — intro only)**: Haiku 4.5 in Batch mode, one
  request per subscriber, producing a single personalized intro
  paragraph. Body items rendered from existing DB summaries verbatim.
- **Iterative build**: v1 ships with intro-only LLM. Pipeline, output
  schema, and template are deliberately structured so per-item blurbs
  and a curated feed page slot in without a refactor.
- **Email provider**: Postmark. Single account. Transactional stream for
  verification emails *and* `mail_admins()` ops alerts. Broadcast stream
  for digests. The Postmark stream split exists exactly so digest
  reputation incidents can't contaminate the transactional channel that
  ops alerts depend on.
- **Email storage**: plain unique column + DB-at-rest encryption
  (Hetzner LUKS); never log raw emails; rate-limit signup; HMAC-signed
  unsubscribe tokens.
- **CAN-SPAM postal address**: confirmed available.

## Architecture

### Cross-cutting additions

- **`settings.ADMINS`** — `[("Name", "email@…")]`, read at Django startup.
  Used by `mail_admins()` (Phase 3 onwards) and by the
  `AdminEmailHandler` in Django's logging config.
- **`EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"`** plus
  `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
  `EMAIL_USE_TLS`, `SERVER_EMAIL` — added in Phase 3 when Postmark is
  wired. Django's stdlib SMTP path is what `mail_admins()` walks
  through. The digest pipeline uses `postmarker` directly (so it can
  pick streams and templates); ops `mail_admins()` flows through the
  default SMTP backend pointing at the same Postmark account.
- **`HEALTHCHECKS_PING_URL_*` env vars** — one per cron job, read by the
  wrapper scripts. Empty/unset = no pings (dev environments).

### Phase 1 only (Healthchecks + exit codes)

Standalone. No Django settings changes beyond optional env vars consumed
by shell wrappers. No new Django app. No model changes. No SDK installs.

### Phase 2+ — `digests/` Django app

Created alongside `seattle_app/` and `reps/`. Wired into `INSTALLED_APPS`
in `seattle_app/settings.py:43`.

#### Models (`digests/models.py`)

- **`Subscriber`**
  - `email` (EmailField, unique, db_index). Stored plaintext; protected
    by DB-at-rest encryption and access control. Never logged.
  - `status` (CharField: `pending` / `active` / `unsubscribed` /
    `bounced` / `complained`).
  - `verification_token` (CharField, 43 chars, `secrets.token_urlsafe(32)`,
    unique, nullable after verification).
  - `unsubscribe_token_version` (int, default 1). Combined with `email` +
    `settings.SUBSCRIBER_TOKEN_SECRET` via HMAC-SHA256 to derive
    stateless unsubscribe/manage tokens. Bumping the version revokes
    outstanding links per-user.
  - `created_at`, `verified_at`, `last_sent_at`, `last_bounce_at`.

- **`SubscriberPreferences`** (OneToOne → `Subscriber`)
  - `weekly_enabled` (bool, default True)
  - `daily_enabled` (bool, default False)
  - `issue_areas` (JSONField, list of strings) — validated against
    `BILL_TAG_VOCABULARY` from `seattle_app/services/claude_service.py`.
  - `followed_reps` (M2M → `opencivicdata.core.Person`)
  - `followed_bills` (M2M → `opencivicdata.legislative.Bill`)
  - `district` (FK → `reps.District`, nullable). Set either by user
    picking from dropdown or by reusing the existing address →
    district geocoder in `reps/services.py` (Nominatim + PostGIS
    `contains_point`, see `reps/models.py:151`).

- **`DigestSend`** — append-only log
  - `subscriber` FK, `cadence`, `sent_at`, `item_count`,
    `postmark_message_id`, `compose_batch_id` (Anthropic batch this
    came from), `bounce_status` (set by webhook).
  - `matched_item_ids` (JSONB list of `{type, id}`) — the items that
    went into this digest. Snapshot, not a live query. Used by the
    future feed page; cheap to store.
  - `llm_payload` (JSONB, nullable) — the parsed Haiku output for this
    send (`{intro}` in v1, `{intro, item_blurbs}` later). Stored so we
    can re-render, debug, or surface the personalized intro on the
    future feed page without a second LLM call.
  - Used for dedup (don't send the same cadence twice in one day),
    audit, cost attribution, and as the snapshot read by future
    surfaces (feed page, "view in browser" link).

Migrations live in `digests/migrations/`. PostgreSQL `citext` for `email`
to make uniqueness case-insensitive.

#### Compose pipeline — mirrors `summarize_legislation.py`

Two new management commands following the exact two-phase pattern in
`seattle_app/management/commands/summarize_legislation.py`:

1. **`python manage.py compose_digests --cadence weekly|daily [--dry-run] [--limit N]`**
   - Loads state from `data/compose_digests_<cadence>_state.json` (same
     convention as `data/summarize_legislation_state.json`).
   - If an in-flight batch exists for this cadence, poll and process.
   - Otherwise build candidate list: subscribers with `status='active'`,
     the relevant cadence flag set, `last_sent_at` not within window.
   - For each subscriber, query the personalization window:
     - Weekly: items new/updated in last 7 days.
     - Daily: items new/updated since their `last_sent_at`.
   - Match against prefs (UNION of all four dimensions): bills tagged
     with any `issue_area`, sponsored by a followed rep, in the
     subscriber's district (via committee/sponsor → district mapping),
     or in `followed_bills`. Same for `EventSummary` (filter by
     committee membership) and notable rep actions (`RepSummary`
     updates).
   - Skip daily users with zero matches. Weekly users with zero
     matches get a short "quiet week in council" template (no LLM
     call needed).
   - Build Anthropic batch requests, one per subscriber:
     - `custom_id = f"sub-{subscriber.id}"` (matches Anthropic's
       `[a-zA-Z0-9_-]{1,64}` regex without encoding gymnastics).
     - `system`: cached style guide + role + JSON output rules.
       `cache_control: {"type": "ephemeral"}`.
     - `messages`: compact JSON with the subscriber's prefs
       (anonymized — no email, just preferences) and the matched
       items (id, title, type, DB summary text, dates).
     - `output_config.format.type = "json_schema"` with a v1 schema of
       `{intro: str}`. Wrapped behind a helper
       `digests/services/llm_schema.py::compose_schema(include_blurbs: bool)`
       so the per-item-blurb expansion in a later phase is a one-line
       config flip rather than a rewrite.
     - `thinking`: omitted. `_supports_adaptive_thinking()` already
       returns False for Haiku, and Haiku 4.5 400s on the parameter.
   - `client.messages.batches.create(requests=requests)`. Persist
     `batch_id`, submitter info, and the list of
     `(subscriber_id, matched_item_ids)` pairs into the state file.

2. **`python manage.py send_digest_batches`**
   - Polls all open batch state files; for each batch with
     `processing_status == "ended"`, iterate
     `client.messages.batches.results(batch_id)`.
   - For each succeeded result, render the email (HTML + plaintext
     multipart) using Django templates in `digests/templates/email/`.
     The LLM-generated `intro` goes at the top. The body is one
     section per matched item, each rendered as title + date +
     existing DB summary verbatim — no LLM content per item in v1.
     Templates include an `{% if item_blurbs %}` block (empty in v1)
     so per-item blurbs will render once the schema flag is flipped.
   - Persist `intro` onto `DigestSend.llm_payload` JSONB so the same
     content can be re-rendered later.
   - POST to Postmark `/email/withTemplate` (or `/email` with rendered
     HTML) on the **broadcast** stream. Capture `MessageID`.
   - Insert a `DigestSend` row inside a transaction with the Postmark
     call's outcome.
   - Failures (Postmark 4xx, hard bounces) flip subscriber status to
     `bounced`; webhook below handles async bounces.
   - On `error_count > 0`, exits non-zero (same pattern Phase 1
     establishes for the summarize_* commands) and calls
     `mail_admins()`. Healthchecks ping fires accordingly via the
     wrapper.

#### Subscriber-facing endpoints (`digests/views.py`, `digests/urls.py`)

- `POST /api/digests/subscribe` — body: `{email, weekly_enabled, daily_enabled, issue_areas[], followed_rep_ids[], followed_bill_ids[], district_id|address}`.
  Rate-limited 5/hour per IP and 1/hour per email hash via `django-ratelimit`.
  Honeypot field on the form. Creates `Subscriber(status='pending', verification_token=...)`,
  sends "confirm your subscription" email through Postmark, returns 202.
- `GET /digests/confirm?token=...` — server-rendered HTML success page (not
  the React app). Flips `status='active'`, clears `verification_token`,
  sets `verified_at`.
- `GET /digests/manage?token=...` — verifies HMAC token, sets a short-lived
  session cookie scoped to the subscriber, redirects to the React
  `/digests/manage` route.
- `POST /api/digests/preferences` — requires the session cookie above.
  Updates `SubscriberPreferences`.
- `POST /digests/unsubscribe?token=...` — verifies HMAC, flips status.
  Supports one-click via
  `List-Unsubscribe-Post: List-Unsubscribe=One-Click` header (Gmail/Yahoo
  bulk-sender requirement, Feb 2024).
- `POST /api/webhooks/postmark` — signature-verified webhook for bounces,
  complaints, opens. CSRF-exempt; verifies Postmark signature header.

#### Frontend

- `<SubscribeForm>` React component on the homepage and footer.
  Multi-step: email → topics → reps/bills/district → confirm.
- `<DigestPreferences>` page at `/digests/manage`. Reuses the same form
  components.

#### Cron entries (`scheduler-crontab`)

```
# Compose weekly digest batch Sunday 6 AM Pacific.
0 6 * * 0 . /etc/cron-env && cd /app && /app/scripts/compose_and_send_digests.sh weekly >> /var/log/cron/digests.log 2>&1

# Compose daily digest batch every weekday morning at 7 AM Pacific.
0 7 * * 1-5 . /etc/cron-env && cd /app && /app/scripts/compose_and_send_digests.sh daily >> /var/log/cron/digests.log 2>&1
```

The shell wrapper runs `compose_digests --cadence ...`, sleeps briefly,
then loops `send_digest_batches` until the batch is done. Digests run
after the 2 AM `update_seattle.sh` sync and 3 AM `poll_llm_batches.sh`,
so the DB has the latest summaries.

## Designed for extension (digest project)

v1 ships the minimum useful product: a personalized intro paragraph plus a
templated body of matched items. Two follow-ups are likely; the v1 design
intentionally leaves space for both.

### Future expansion A — per-item LLM blurbs in the email

Each matched item gets a 1-2 sentence personalized framing line above its
DB summary. Already supported by `compose_schema(include_blurbs=True)`,
the email template's `{% if item_blurbs %}` block, and the JSONB
`DigestSend.llm_payload` column. Implementation work: write the blurb
portion of the system prompt, add snapshot tests, roll out behind a
`DIGEST_INCLUDE_BLURBS` env flag.

### Future expansion B — curated, persisted, non-LLM feed page

Route `/digests/feed/<digest_send_id>?u=<subscriber_hmac>`, server-rendered
Django template, two sections (snapshot of the digest from
`DigestSend.matched_item_ids` + a fresh "since then" query). No LLM —
timeliness over framing. Reuses HMAC token machinery and the persisted
`matched_item_ids`.

### Future expansion C — daily cadence

Already accommodated by `SubscriberPreferences.daily_enabled` and a
parameterized `--cadence daily`. Not in v1 to limit volume during
Postmark domain warmup.

### Future expansion D — Slack ops channel

Healthchecks dashboard toggle, no code change. Optional follow-on: a
Claude-on-Slack loop that reads alerts from a channel, opens a PR with
a proposed fix. Requires a separate plan doc.

## Security

### Phase 1 only

Healthchecks receives: job names (e.g., "councilmatic-poll-llm-batches"),
ping timestamps, and the last ~9 KB of stdout/stderr on failure pings.
Operational notes:

- Pick job names that don't leak internals (don't name them after secrets
  or customers).
- The failure-ping body is the cron log tail. If anything PII-shaped ever
  enters those logs in the future, the redaction filter shipping in Phase
  2 will catch it before it leaves the box. For Phase 1 the cron logs
  contain only IDs and counts; no emails or names.
- Healthchecks ping URLs are unguessable UUIDs but should still be
  treated as secrets — anyone with one can fake-ping the job and silence
  the alert. Store in `.env`, never commit.

### Phase 2+ (digest project)

1. **At-rest encryption**: Hetzner doesn't encrypt volumes by default.
   Operational task: enable LUKS on the Postgres data volume before
   launching the feature. Documented in `DEPLOY.md` as a launch
   checklist item.
2. **No raw emails in logs**: configure `logging.Filter` that masks
   anything matching the standard email regex in Django logs. Use
   `subscriber.id` everywhere in code paths. Implement in Phase 2.
3. **Backups**: pg_dump backups must be encrypted (age or GPG) and
   stored off the production host. Documented in `DEPLOY.md`.
4. **Tokens**:
   - Verification token: one-shot, `secrets.token_urlsafe(32)`, stored
     in DB, cleared after use.
   - Manage/unsubscribe token: stateless HMAC-SHA256(`f"{subscriber.id}:{subscriber.unsubscribe_token_version}"`,
     key=`SUBSCRIBER_TOKEN_SECRET`). Stateless = no DB lookup needed;
     revocable per-user by bumping `unsubscribe_token_version`;
     revocable globally by rotating the secret.
   - Use `hmac.compare_digest()` for verification.
5. **Rate-limit signup**: `django-ratelimit` 5/hour per IP and 1/hour
   per email hash. Add `Retry-After` header on rejection.
6. **Honeypot field** on subscribe form (no CAPTCHA — accessibility
   concern; honeypot is sufficient for the threat model).
7. **Webhook security**: Postmark sends a signature header; verify
   against `POSTMARK_WEBHOOK_SECRET` with `hmac.compare_digest`.
8. **Postmark API key**: read from `POSTMARK_SERVER_TOKEN` env var;
   never committed; rotated through Postmark's dashboard.
9. **Right-to-delete**: a scheduled command `purge_unsubscribed`
   hard-deletes subscriber rows 30 days after unsubscribe
   (configurable). The unsubscribe handler also accepts a "delete my
   data immediately" option.
10. **Admin access**: don't expose subscriber records in the Django
    admin. If admin visibility is needed for debugging, mask the email.
11. **No PII to Anthropic**: the Batch request payload sent to
    Anthropic for each subscriber contains only `subscriber.id` (in
    `custom_id`) and their preferences and matched items — no email
    address, no name, no IP, no district address. Enforced in
    `compose_digests` by constructing the per-user payload from a
    whitelisted set of fields and covered by a unit test that asserts
    no email-shaped string appears in the request body.
12. **Postmark tracking disabled**: open-tracking pixels and
    click-tracking redirects explicitly disabled in the Postmark API
    call (`TrackOpens: false`, `TrackLinks: "None"`).
13. **No third-party sale or sharing**: codified as project policy;
    only outbound destinations for subscriber data are Postmark
    (delivery) and Anthropic (preferences only, no PII).

## Costs

### Phase 1

- Healthchecks.io free tier: $0 (20 checks; we use ~5).
- Postmark: not provisioned yet — no cost.
- Marginal infrastructure cost: zero.

### Phase 2+ (digests)

Per-email cost is dominated by Postmark, then Haiku. v1 is intro-only,
so each Haiku call at send time is ~3,000 input tokens (mostly cached)
and ~200 output tokens — **~$0.001 per send** in Haiku 4.5 Batch.

Postmark is $15/mo flat for the first 10k emails, then $1.25 per
additional 1k.

#### Scenario A — v1: weekly-only, intro-only LLM

| Subscribers | Emails / mo | Postmark | Haiku (intro only, batched) | Total |
|---|---|---|---|---|
| 100  |    400 | $15 | ~$0.50 | **~$16/mo** |
| 500  |  2,000 | $15 | ~$2    | **~$17/mo** |
| 1,000|  4,000 | $15 | ~$4    | **~$19/mo** |
| 2,500| 10,000 | $15 | ~$10   | **~$25/mo** |
| 5,000| 20,000 | $27.50 ($15 + $12.50 for 10k overage) | ~$20 | **~$48/mo** |

Per-subscriber-per-month at the 1k-subscriber level: **~$0.019**.
Postmark's flat fee dominates until ~2k subscribers.

#### Scenario B — future: weekly + daily-when-news, intro-only

Adds daily cadence as an opt-in. Assumes ~20% of weekly subscribers
also opt in to daily, and daily sends fire ~3 days a week per user.

| Subscribers | Daily users | Emails / mo | Postmark | Haiku | Total |
|---|---|---|---|---|---|
| 100  | 20  |    640 | $15 | ~$0.70 | **~$16/mo** |
| 500  | 100 |  3,200 | $15 | ~$3    | **~$18/mo** |
| 1,000| 200 |  6,400 | $15 | ~$6    | **~$21/mo** |
| 2,500| 500 | 16,000 | $22.50 | ~$16 | **~$39/mo** |

#### Scenario C — future: weekly + intro + per-item blurbs

For reference: per-send cost roughly triples (output tokens ~200 → ~600).
At 1k weekly subscribers that's ~$12/mo of Haiku, taking the total to
**~$27/mo**.

#### Ops alerting marginal cost

Once Postmark exists, `mail_admins()` traffic is ≤5 emails/month even on
bad weeks. Negligible against the broadcast volume; well under the 10k
free-tier ceiling.

### Verdict

- Phase 1 alone: $0 marginal.
- Digest v1 at 1k subscribers: **~$19/mo**, of which $15 is unavoidable
  Postmark base.
- All scaling is linear.

## Legal / compliance

### Phase 1

Not applicable. Internal monitoring of our own infrastructure.

### Phase 2+ (digests)

1. **CAN-SPAM** (federal, US):
   - Non-deceptive headers and subject lines.
   - Identify as a recurring update (footer wording).
   - Physical postal address in every email footer — threaded via
     `settings.DIGEST_POSTAL_ADDRESS`.
   - Clear opt-out: unsubscribe link in every email; honored immediately.
2. **Gmail / Yahoo bulk-sender requirements** (Feb 2024 onward):
   - `List-Unsubscribe` and
     `List-Unsubscribe-Post: List-Unsubscribe=One-Click` headers —
     Postmark adds these if configured.
   - SPF, DKIM, DMARC on `seattlecouncilmatic.org`. DMARC at minimum
     `p=none` to start, escalate to `quarantine`. Operational task;
     add to `DEPLOY.md`.
   - Keep spam rate <0.3% (Postmark dashboard alerts).
3. **Washington state**:
   - **CEMA** (RCW 19.190) — Washington's anti-spam statute. Compliance
     is automatic if we follow CAN-SPAM and use accurate sender info.
   - No comprehensive WA consumer privacy law covers this scenario.
4. **GDPR**: unlikely audience; right-to-delete and one-click
   unsubscribe satisfy the spirit.
5. **Double opt-in** (chosen): defeats subscription-bomb abuse and
   gives legal cover that we have explicit consent.
6. **Privacy policy update**: extend the Wagtail CMS privacy page to
   disclose, prominently:
   - We do not sell, rent, share, or trade subscriber data with anyone.
   - We do our best to protect what we collect (LUKS, access control,
     encrypted backups, no raw emails in logs, TLS in transit, 30-day
     deletion after unsubscribe).
   - What we collect: email address, digest preferences, Postmark
     delivery telemetry.
   - What we send: weekly (and optionally daily) digest emails.
   - Retention: hard-delete 30 days after unsubscribe. Immediate
     deletion available on request.
   - Subprocessors: Postmark (delivery) and Anthropic (intro/blurbs
     composition — preferences only, no email address or identifier).
   - Your rights: update preferences, unsubscribe, or request deletion
     at any time.
   - No tracking pixels or click trackers (Postmark offers these; we
     disable them).
7. **Terms of service**: similar update — single line that the digest
   service is provided as-is.

## Files to add or modify

### Phase 1 scope only

**Modify (no new files needed):**

- `seattle_app/management/commands/summarize_legislation.py`,
  `summarize_events.py`, `summarize_reps.py`, `tag_bill_issue_areas.py`,
  `summarize_smc_sections.py` — at the end of `_process_results`, after
  the state file is written, raise `CommandError` if `errors` is
  non-empty. Django's `CommandError` causes `sys.exit(1)`. The state
  file is already written, so the next run still picks up where this
  one left off; the exit code is just the signal to cron.
- `scripts/poll_llm_batches.sh`, `scripts/update_seattle.sh`,
  `scripts/update_reps.sh`, `scripts/backup-db.sh` — add Healthchecks
  start/success/fail pings. The wrapper sketch:

  ```bash
  URL="${HEALTHCHECKS_PING_URL_POLL_LLM_BATCHES:-}"
  ping() { [ -n "$URL" ] && curl -fsS -m 10 --retry 3 "$URL$1" >/dev/null 2>&1 || true; }
  trap 'rc=$?; if [ $rc -ne 0 ]; then tail -c 9000 "$LOG" | curl -fsS -m 10 --retry 3 --data-binary @- "$URL/fail" >/dev/null 2>&1 || true; else ping; fi; rm -f "$LOG"' EXIT
  LOG=$(mktemp)
  ping /start

  # ... existing command body, captured via tee for the failure-ping body ...
  python manage.py poll_llm_batches 2>&1 | tee -a "$LOG"
  ```

  Exact form per-script will vary slightly; the pattern is the same.
  Unset URL = no pings (dev environments).
- `.env.example` — add `HEALTHCHECKS_PING_URL_UPDATE_SEATTLE`,
  `HEALTHCHECKS_PING_URL_POLL_LLM_BATCHES`,
  `HEALTHCHECKS_PING_URL_UPDATE_REPS`,
  `HEALTHCHECKS_PING_URL_BACKUP_DB` placeholders with a comment
  documenting how to obtain them from the Healthchecks dashboard.
- `DEPLOY.md` — new "Ops alerting" section: create Healthchecks
  account, configure check schedules to match cron (with appropriate
  grace periods — 1 hour for the 2 AM sync, 30 min for the 3 AM poll),
  copy ping URLs into `.env`, set notification channels (email; Slack
  later). Document how to silence/snooze a known-failing check.

**Phase 1 explicitly does NOT touch:**
- `seattle_app/settings.py` (no `ADMINS`, no `EMAIL_BACKEND` — those
  come with Postmark in Phase 3).
- The `digests/` app (doesn't exist yet).
- The Postgres schema.
- `requirements.txt`.

### Phase 2+ scope

**Add:**
- `digests/` (new Django app): `models.py`, `views.py`, `urls.py`,
  `admin.py` (intentionally limited), `apps.py`,
  `services/postmark.py`, `services/personalization.py`,
  `services/tokens.py`,
  `services/llm_schema.py` (the `compose_schema(include_blurbs)`
  helper), `templates/email/weekly_digest.{html,txt}`,
  `templates/email/daily_digest.{html,txt}` (scaffold only),
  `templates/email/verify.{html,txt}`,
  `management/commands/compose_digests.py`,
  `management/commands/send_digest_batches.py`,
  `management/commands/purge_unsubscribed.py`,
  `migrations/0001_initial.py`.
- `digests/tests/` — model validators, token round-trip,
  personalization match query, send pipeline with mocked Anthropic +
  Postmark, `compose_schema` shape under both flag values, redaction
  filter, "no PII in Anthropic payload" assertion.
- `frontend/src/components/SubscribeForm.{jsx,css}`,
  `frontend/src/pages/DigestPreferences.{jsx,css}`.
- `scripts/compose_and_send_digests.sh` (wrapper with Healthchecks
  pings from Phase 1).

**Deferred to Phase 6/7 (not in v1):**
- Per-item blurb prompt + snapshot tests of the blurbed HTML render.
- `digests/views.py::feed_view`, `digests/templates/feed/digest_feed.html`,
  "look up my digest" form.

**Modify:**
- `seattle_app/settings.py` — `INSTALLED_APPS` (`'digests'`); add
  `ADMINS = [...]`, `EMAIL_BACKEND`, `EMAIL_HOST` (Postmark SMTP),
  `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_PORT`,
  `EMAIL_USE_TLS`, `SERVER_EMAIL`, `DEFAULT_FROM_EMAIL`,
  `CLAUDE_DIGEST_MODEL`, `POSTMARK_SERVER_TOKEN`,
  `POSTMARK_WEBHOOK_SECRET`, `SUBSCRIBER_TOKEN_SECRET`,
  `DIGEST_POSTAL_ADDRESS`, `DIGEST_FROM_EMAIL`. Override the default
  `LOGGING` dict: add the email-redaction filter, and omit
  `AdminEmailHandler` from the `django` logger (we use `mail_admins()`
  only from explicit call sites — see "Logging handler scope" in
  Decisions already made).
- `seattle_app/urls.py` — include `digests.urls` at `/api/digests/`
  and `/digests/`.
- `scheduler-crontab` — add weekly + daily entries.
- `.env.example` — add the new env vars.
- `frontend/src/App.jsx` — register the `/digests/manage` route.
- `seattle_app/templates/base.html` — homepage subscribe widget mount
  if desired.
- `councilmatic_cms` privacy / terms pages — content updates.
- `DEPLOY.md` — launch checklist (LUKS, DMARC, Postmark approval,
  postal address), runbook for subscriber data deletion, secret
  rotation steps.
- `requirements.txt` — `postmarker`, `django-ratelimit`.
- The five batch commands modified in Phase 1 — add `mail_admins()`
  call when `errors` is non-empty, with a body containing the
  per-request error strings. Phase 1's `CommandError` raise still
  trips Healthchecks; this just adds a parallel rich email.

## Existing code to reuse

- Two-phase batch command pattern: `summarize_legislation.py` submit
  phase + poll/process phase. Mirror exactly.
- Custom-id encoding helpers: `summarize_legislation.py:78-91`. Adapt
  to `f"sub-{id}"`.
- State file load/save helpers in `summarize_legislation.py`.
- Ephemeral system-prompt caching idiom in `summarize_legislation.py`.
- Adaptive-thinking guard: `seattle_app/services/claude_service.py`
  `_supports_adaptive_thinking()` (returns False for Haiku → skip the
  `thinking` param entirely).
- Batch-error formatting: `format_batch_error()` in
  `seattle_app/services/claude_service.py` (added PR #198). Used by
  both Phase 1 (output of failed batches in state file is already
  diagnosable) and Phase 3 (`mail_admins()` body builder reads the
  formatted strings).
- JSON-schema `output_config` idiom in `summarize_legislation.py`.
- Bill tag vocabulary (validate user prefs against this):
  `seattle_app/services/claude_service.py` `BILL_TAG_VOCABULARY`.
- District / address geocoding: `reps/models.py`
  `District.contains_point` and the Nominatim wrapper in
  `reps/services.py`.
- Existing DB summary models for digest body: `LegislationSummary`,
  `EventSummary` in `seattle_app/models.py`; `RepSummary` in
  `reps/models.py`.

## Phased rollout

**Phase 1 — Ops alerting & liveness (its own PR; ships first; standalone)**

Solves the "summarize_legislation silently dropped 19 bills last night"
class of failure. Delivers as a single PR independent of every later
phase. Three pieces:

1. Each of the five batch management commands raises `CommandError`
   when its `errors` list is non-empty after `_process_results` (so
   Django exits non-zero, the wrapper script's `set -e` triggers,
   the wrapper's `EXIT` trap fires a `/fail` ping).
2. Each cron wrapper script (`update_seattle.sh`, `poll_llm_batches.sh`,
   `update_reps.sh`, `backup-db.sh`) gets `/start`, `/<uuid>`,
   `/<uuid>/fail` pings keyed on a per-script
   `HEALTHCHECKS_PING_URL_*` env var. Unset env var = no pings.
3. Operational tasks (not code): create the Healthchecks account,
   configure five checks with appropriate cron schedules and grace
   periods, set notification channel to email, copy ping URLs into
   `.env` in production. Documented in `DEPLOY.md`.

Verification (Phase 1 only):
- Local: run a batch command against a fake error condition (e.g.,
  edit one bill's `extracted_text` to something that triggers a
  schema-validation error), confirm command exits non-zero and the
  wrapper would have pinged `/fail`.
- Staging: set up a dev Healthchecks check, run the wrapper with the
  URL set, confirm pings arrive (start → success on clean run; start
  → fail on injected failure).
- Production: configure all five checks, watch the next 2 AM / 3 AM
  cycle, confirm green pings.

**Phase 2 — Subscription plumbing, no email yet**
- `digests` app, models, migrations.
- Subscribe / confirm / manage / unsubscribe endpoints with HMAC
  tokens.
- Frontend subscribe form + preferences page.
- "Sending" stubbed: writes a `DigestSend` row but doesn't actually
  call Postmark. Lets us QA the flow end-to-end internally.
- Add email-redaction logging filter early so the moment a stack
  trace touches a `Subscriber`, addresses don't leak.

**Phase 3 — Postmark wiring (and ops mail_admins layered on)**
- Postmark account, sending domain, SPF/DKIM/DMARC.
- Templates (HTML + plaintext).
- Verification email actually sent via Postmark (transactional stream).
- Webhook + bounce handling.
- Django `settings.ADMINS`, `EMAIL_BACKEND` SMTP, `SERVER_EMAIL`
  pointed at the Postmark transactional stream. `mail_admins()` is
  now functional.
- Wire `mail_admins()` into the five batch commands' error path
  (parallel to the `CommandError` raise Phase 1 added). Subject:
  `"<command>: N of M failed"`; body: per-request error strings from
  `format_batch_error()`.
- Override Django's default `LOGGING` dict to exclude
  `AdminEmailHandler` from the `django` logger so `mail_admins()`
  fires from explicit call sites only — never automatically on a
  random `logger.error(...)` from app or library code. Rationale in
  "Decisions already made → Logging handler scope."
- Launch a closed beta where the team subscribes and confirms the
  round-trip.

**Phase 4 — Digest composition (templated, no LLM yet)**
- Personalization match queries.
- `compose_digests` writes templated digests (no LLM) and
  `send_digest_batches` sends them. Snapshot `matched_item_ids` onto
  `DigestSend`.
- Cron entries added (with Healthchecks pings from Phase 1).
- Weekly digest goes out to the beta cohort. Daily cadence stays off.

**Phase 5 — LLM intro (digest v1 ship)**
- Add the Haiku batch step to `compose_digests` with
  `compose_schema(include_blurbs=False)` — output is `{intro: str}` only.
- Style guide + cached system prompt.
- `send_digest_batches` reads the LLM result, persists it to
  `DigestSend.llm_payload`, and renders the intro at the top.
- Beta evaluation gate. If yes, open public signups.

**Phase 6 (later) — Per-item LLM blurbs**
- Flip `compose_schema(include_blurbs=True)` behind a
  `DIGEST_INCLUDE_BLURBS` flag.
- Light up the `{% if item_blurbs %}` block.
- Manual A/B over unsubscribe-click or survey.

**Phase 7 (later) — Curated, persisted, non-LLM feed page**
- Server-rendered `/digests/feed/<digest_send_id>` view,
  magic-link-authenticated via existing HMAC token helpers.
- Snapshot section + a fresh "since then" query.
- No LLM on this page; cache-friendly; robots-disallow.

## Verification

### Phase 1

1. Edit a batch command's input (or temporarily monkey-patch
   `format_batch_error` to inject a fake error) so a batch run will
   have `error_count > 0`. Run the management command. Confirm:
   - Exit code is non-zero.
   - State file's `errors` list is populated.
   - Database is not corrupted.
2. With a dev Healthchecks check configured: run the wrapper script
   under both conditions (clean success, induced failure). Confirm
   that the Healthchecks dashboard shows `up` then `down` and that an
   email arrives for the down event.
3. Stop the scheduler container. Confirm Healthchecks fires a
   "missed check-in" alert after the configured grace period
   without any explicit fail ping (this is the dead-man's-switch
   case — catches the failure mode where the box itself is gone).
4. Confirm setting `HEALTHCHECKS_PING_URL_*=` (empty) cleanly disables
   pings without errors (dev workflow).

### Phase 5 (digest v1)

1. `python manage.py test digests` — unit tests for token round-trip,
   preference validation, personalization match query, dedup of
   repeated daily sends, `compose_schema(include_blurbs=False)` shape,
   redaction filter, and the "no PII in Anthropic payload" assertion.
2. `python manage.py compose_digests --cadence weekly --dry-run --limit 3` —
   prints what would be submitted, no API calls.
3. `python manage.py compose_digests --cadence weekly --limit 3`
   against a staging Postmark sandbox → run `send_digest_batches` →
   confirm three emails arrive at team addresses with a personalized
   intro + verbatim DB summaries.
4. Inspect the corresponding `DigestSend` rows: `matched_item_ids`
   populated, `llm_payload` contains the intro string.
5. Click the unsubscribe link → confirm subscriber status flips, that
   a subsequent `compose_digests` excludes them, and that the
   one-click POST endpoint works (curl with the
   `List-Unsubscribe-Post` header value).
6. Generate a hard-bounce test through Postmark's sandbox → confirm
   the webhook fires and the subscriber row flips to `bounced`.
7. `python manage.py purge_unsubscribed --dry-run` — confirms
   candidates for deletion.
8. `mail-tester.com` score on a real-content digest: target ≥ 9/10.
9. Postmark dashboard: spam complaint rate <0.3%, bounce rate <2% on
   the beta cohort before opening signups publicly.
10. Eyeball the intro for ~10 real subscribers' preference sets —
    does it actually feel personalized, or generic? Explicit decision
    gate before opening public signups.

## Launch blockers (operational, not code)

### Phase 1

- Create the Healthchecks.io account and five checks
  (`update_seattle`, `poll_llm_batches`, `update_reps`, `backup_db`;
  plus `compose_digests_*` when Phase 4 lands).
- Configure cron schedules + grace periods on each check.
- Copy ping URLs into production `.env`.
- Set the notification channel (email; Slack later).

### Phase 5 (digest v1)

- LUKS on the Postgres volume (or accept and document the risk).
- DMARC/DKIM/SPF on the sending domain.
- Postmark approval for the sending domain (typically same-day).
- Postal address threaded into `DIGEST_POSTAL_ADDRESS`.
- Privacy policy + terms updates published before the first public
  subscribe link goes live.
- Decide retention window for unsubscribed records (default: 30 days).

## Open questions / decisions to revisit

- **`.gitignore` carve-out for `.claude/plans/`** — currently
  `.claude/*` is fully ignored, so plan files like this one don't
  travel with ephemeral session clones. A one-line `.gitignore`
  addition (`!.claude/plans/`) would make plans visible to remote
  sessions without exposing the rest of `.claude/`. Not in Phase 1
  scope; flagged for separate decision.
- **Admins in DB vs. settings** — settled on settings.ADMINS for
  Phase 3. Revisit only if (a) admin list rotates more than yearly,
  (b) per-admin alert-type subscriptions become important, or (c)
  non-engineers need to manage the list. None of these are on the
  near-term roadmap.
- **Claude-on-Slack diagnose-and-PR loop** — plausible follow-on to
  the basic Slack alerting in "Future expansion D." Requires its own
  plan doc; out of scope here.
- **One Postmark account vs. two** — chose one with stream separation.
  Reversing later (splitting transactional ops alerts into their own
  account for stronger reputation isolation) is painful but doable
  if a digest-side reputation incident ever forces the issue.
