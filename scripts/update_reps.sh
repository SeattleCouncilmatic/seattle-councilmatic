#!/bin/bash
set -e  # Exit on error

# Weekly rep refresh — bios from seattle.gov and the LLM rep-summary
# card. Memberships change rarely (every few years per seat) so daily
# isn't worth it; this fires once a week.
#
# The summary submit lives here; polling + persistence happens in
# `poll_llm_batches.sh` (which runs daily and no-ops on days when
# no rep batch is in flight). Cycle is: Sun 2:30 AM submit → Sun
# 3 AM poll picks it up (covered by the daily poll cron).

echo "================================"
echo "Seattle Councilmatic Rep Refresh"
echo "================================"

echo ""
echo "1. Scraping rep bios from seattle.gov..."
python manage.py scrape_rep_bios

echo ""
echo "2. Submitting rep-summary batch (will be polled at 3 AM)..."
python manage.py summarize_reps

echo ""
echo "================================"
echo "✓ Rep refresh complete!"
echo "================================"
