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

# Steps 3-7 below were added when wiring the LLM pipelines into the
# nightly cron. Each command is idempotent — runs against new rows
# only (skips items that already have a tag/summary/transcript).
# The Batch commands (`tag_bill_issue_areas`, `summarize_legislation`,
# `summarize_events`) only SUBMIT here; polling + persistence happens
# in `poll_llm_batches.sh` an hour later.

echo ""
echo "3. Extracting plain text for new bills..."
python manage.py extract_bill_text

echo ""
echo "4. Extracting Seattle Channel transcripts for new past meetings..."
python manage.py extract_event_transcripts

echo ""
echo "5. Submitting LLM batches (will be polled at 3 AM)..."
python manage.py tag_bill_issue_areas
python manage.py summarize_legislation
python manage.py summarize_events

echo ""
echo "================================"
echo "✓ Update complete!"
echo "================================"
