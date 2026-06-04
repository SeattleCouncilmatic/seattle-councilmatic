#!/bin/bash
set -e  # Exit on error

# This drain pass is its own PipelineRun (issue #208): it processes the batches
# the preceding cycle submitted, so they end up with processed_in_run = this run
# while their submitted_in_run stays the earlier cycle.
export PIPELINE_RUN_KEY="run_$(date -u +%Y%m%dT%H%M%SZ)"
export PIPELINE_RUN_KIND="offset-drain"

# Offset drain pass, run ~1h after each 6h `update_seattle.sh` cycle:
# polls + persists any batch that cycle submitted so results land
# without waiting for the next cycle.
#
# Each Batch command (`tag_bill_issue_areas`, `summarize_legislation`,
# `summarize_events`, `summarize_reps`) is drain-then-submit: it polls +
# persists an in-flight batch, then submits a new one for any
# unprocessed rows. Here no scrape has run since the cycle, so the
# candidate queries are empty and this is effectively a pure drain — it
# persists the in-flight batch and no-ops the submit ("No rows need …").
#
# `summarize_reps` is included so the weekly batch submitted by
# `update_reps.sh` (Sunday 2:30 AM) gets drained on the next pass.

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
