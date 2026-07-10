#!/bin/bash
set -e  # Exit on error

# Compose + deliver one digest cadence (Phases 2-3, #235/#238). Compose
# snapshots matches into pending DigestSend rows and submits the intro
# batch; send polls the batch (up to --wait minutes — batches usually end
# in 5-30), persists the intros, renders, and delivers. Digests still
# waiting at the deadline send WITHOUT the intro on a later run (send's
# LLM_MAX_DELAY caps the wait at 6h; the intro never blocks the digest).
#
# Prod safety before Phase 4: send_digest_batches refuses the SMTP
# transport outside DEBUG (and exits quietly when there's nothing to
# send), so this can sit in the prod crontab now without emailing anyone.
CADENCE="${1:?usage: compose_and_send_digests.sh weekly|daily}"

python manage.py compose_digests --cadence "$CADENCE"
python manage.py send_digest_batches --wait 45
