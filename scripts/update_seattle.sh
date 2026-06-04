#!/bin/bash
set -e  # Exit on error

# Full pipeline cycle — scrape + sync + extract bill text + extract transcripts
# + drain/submit the LLM batches. Orchestrated by the run_pipeline command,
# which brackets the whole cycle in a PipelineRun and records a PipelineStep
# (status, timing, output) per step (issue #214). The run_key is minted inside
# run_pipeline; a stuck/failed step is recorded, not just a silent set -e abort.
python manage.py run_pipeline --kind full-cycle
