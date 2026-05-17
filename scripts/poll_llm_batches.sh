#!/bin/bash
set -e  # Exit on error

# Poll any in-flight Anthropic Batch jobs submitted by the 2 AM
# `update_seattle.sh` run an hour earlier, and persist results.
#
# Each Batch command (`tag_bill_issue_areas`, `summarize_legislation`,
# `summarize_events`, `summarize_reps`) is two-phase: the first
# invocation submits a batch and writes the batch ID to its state
# file; the second invocation polls that batch and (when ended)
# writes results to the DB. Re-running a command does the right
# thing based on its own state file:
#
#   - State file has an in-flight batch_id  → poll + persist (if ended)
#   - State file is empty / batch processed → try to submit (no-op if
#                                              nothing to do)
#
# So calling each command here at 3 AM does the poll for batches
# submitted at 2 AM. If a command has no in-flight batch, it
# attempts a submit; for daily commands that's the same submit that
# already happened at 2 AM (so the bills/events queries return
# empty and it no-ops with "No rows need …").
#
# `summarize_reps` is included even though it's submitted weekly
# (via `update_reps.sh`, not the daily script). Calling it daily
# just polls the weekly batch on the morning after submission and
# no-ops the rest of the week.

echo "================================"
echo "Poll LLM Batches"
echo "================================"

echo ""
echo "1. Polling tag_bill_issue_areas..."
python manage.py tag_bill_issue_areas

echo ""
echo "2. Polling summarize_legislation..."
python manage.py summarize_legislation

echo ""
echo "3. Polling summarize_events..."
python manage.py summarize_events

echo ""
echo "4. Polling summarize_reps..."
python manage.py summarize_reps

echo ""
echo "================================"
echo "✓ Poll cycle complete!"
echo "================================"
