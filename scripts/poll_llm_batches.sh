#!/bin/bash
set -e  # Exit on error

# Offset drain pass ~1h after each full cycle: polls + persists the batches that
# cycle submitted. Its own PipelineRun (kind=offset-drain), so those batches end
# up with processed_in_run = this run while submitted_in_run stays the earlier
# cycle. No scrape runs, so the commands' submit phase finds nothing new.
# Orchestrated + per-step-tracked by run_pipeline (issue #214).
python manage.py run_pipeline --kind offset-drain
