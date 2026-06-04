#!/bin/bash
set -e  # Exit on error

echo "================================"
echo "Seattle Councilmatic Update"
echo "================================"

echo ""
echo "1. Running Pupa scrapers..."
pupa update seattle "$@"

echo ""
echo "2. Syncing to Councilmatic models..."
python manage.py sync_councilmatic

# Steps 3-5 below were added when wiring the LLM pipelines into the
# scheduler. Each command is idempotent — runs against new rows only
# (skips items that already have a tag/summary/transcript). The Batch
# commands (`tag_bill_issue_areas`, `summarize_legislation`,
# `summarize_events`) are drain-then-submit: each run first polls +
# persists any batch still in flight from the previous run, then
# submits a new one for rows scraped since. The offset
# `poll_llm_batches.sh` pass lands results faster between cycles.

echo ""
echo "3. Extracting plain text for new bills..."
python manage.py extract_bill_text

echo ""
echo "4. Extracting Seattle Channel transcripts for new past meetings..."
python manage.py extract_event_transcripts

echo ""
echo "5. Draining prior LLM batches + submitting new ones..."
python manage.py tag_bill_issue_areas
python manage.py summarize_legislation
python manage.py summarize_events

echo ""
echo "================================"
echo "✓ Update complete!"
echo "================================"
