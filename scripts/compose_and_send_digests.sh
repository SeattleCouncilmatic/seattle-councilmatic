#!/bin/bash
set -e  # Exit on error

# Compose + deliver one digest cadence (Phase 2, #235). Compose snapshots
# matches into pending DigestSend rows; send renders and delivers them —
# no LLM batch yet, so the two run back-to-back. Phase 3 inserts the
# Anthropic Batch submit/poll between them (this wrapper grows the poll
# loop, mirroring poll_llm_batches.sh).
#
# Prod safety before Phase 4: send_digest_batches refuses the SMTP
# transport outside DEBUG (and exits quietly when there's nothing to
# send), so this can sit in the prod crontab now without emailing anyone.
CADENCE="${1:?usage: compose_and_send_digests.sh weekly|daily}"

python manage.py compose_digests --cadence "$CADENCE"
python manage.py send_digest_batches
