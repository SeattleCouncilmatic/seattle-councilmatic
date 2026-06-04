#!/bin/bash
set -e  # Exit on error

# Weekly rep refresh — scrape bios from seattle.gov + submit the rep-summary
# batch. Its own PipelineRun (kind=weekly-rep); the offset drain passes poll +
# persist the batch on the next tick. Orchestrated + per-step-tracked by
# run_pipeline (issue #214).
python manage.py run_pipeline --kind weekly-rep
