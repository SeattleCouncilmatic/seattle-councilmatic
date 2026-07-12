"""``DigestLLMClient`` — the single interface all send-time model calls go
through (Phase 3, #238). Mirrors the ``DigestEmailClient`` pattern: callers
depend on the interface, only the provider differs.

Implementations, selected by ``DIGEST_LLM_BACKEND``:

- ``anthropic`` (default): the Message Batches API — one request per
  subscriber, ~50% off, results within minutes at digest volumes.
- ``openai`` (stub): reserved for a provider-hosted OpenAI-compatible OSS
  endpoint (plan "Future expansion D"). Deliberately unimplemented until
  the LLM line item is big enough to matter.
- ``none``: no LLM — compose skips the batch and digests send templated-only
  (Phase 2 behaviour). For dev environments without an API key.

The digest pipeline deliberately does NOT subclass ``BatchPipelineCommand``:
that base couples drain-then-submit into one command keyed by ``BatchRun``
rows, while digests split submit (compose) and poll (send) across two
commands with state on the ``DigestSend`` rows themselves. Result parsing
mirrors ``BatchPipelineCommand.iter_json_results``.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings

from seattle_app.services.claude_service import format_batch_error

logger = logging.getLogger(__name__)

# processing_status values we treat as "keep waiting".
IN_FLIGHT_STATUSES = ("in_progress", "canceling")


class DigestLLMClient:
    """Interface. Implementations raise on transport failure — callers
    degrade to templated-only digests, never block the send."""

    def submit_intro_batch(self, requests: list[dict]) -> str:
        """Submit and return the provider batch id."""
        raise NotImplementedError

    def batch_status(self, batch_id: str) -> str:
        """Provider processing status; ``"ended"`` means results are ready."""
        raise NotImplementedError

    def batch_results(self, batch_id: str) -> dict[str, dict]:
        """``{custom_id: parsed_json}`` for succeeded requests. Failed or
        unparseable requests are logged and omitted — the caller sends
        those digests without an intro."""
        raise NotImplementedError


class AnthropicDigestLLMClient(DigestLLMClient):
    def __init__(self):
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def submit_intro_batch(self, requests):
        batch = self._client.messages.batches.create(requests=requests)
        return batch.id

    def batch_status(self, batch_id):
        batch = self._client.messages.batches.retrieve(batch_id)
        return getattr(batch, "processing_status", "unknown")

    def batch_results(self, batch_id):
        parsed: dict[str, dict] = {}
        for result in self._client.messages.batches.results(batch_id):
            cid = result.custom_id
            if result.result.type != "succeeded":
                logger.warning(
                    "digest intro %s failed: %s",
                    cid, format_batch_error(result.result),
                )
                continue
            text = next(
                (b.text for b in result.result.message.content
                 if b.type == "text"),
                "",
            )
            try:
                parsed[cid] = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("digest intro %s returned non-JSON output", cid)
        return parsed


class OpenAICompatibleDigestLLMClient(DigestLLMClient):
    """Reserved for a provider-hosted OSS endpoint (DeepInfra/Together —
    NOT self-hosted inference). See the plan's trigger criteria before
    building this out."""

    def __init__(self):
        raise NotImplementedError(
            "The OpenAI-compatible digest LLM backend is a planned future "
            "expansion; run with DIGEST_LLM_BACKEND=anthropic (or 'none')."
        )


def get_llm_client() -> DigestLLMClient | None:
    """Client for the configured backend, or ``None`` when the LLM step is
    switched off (backend 'none', or 'anthropic' without an API key —
    a dev environment shouldn't crash the weekly compose over a missing
    key; it just sends templated-only)."""
    backend = settings.DIGEST_LLM_BACKEND
    if backend == "none":
        return None
    if backend == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            logger.warning(
                "DIGEST_LLM_BACKEND=anthropic but ANTHROPIC_API_KEY is unset; "
                "digests will send without intros."
            )
            return None
        return AnthropicDigestLLMClient()
    if backend == "openai":
        return OpenAICompatibleDigestLLMClient()
    raise ValueError(
        f"Unknown DIGEST_LLM_BACKEND {backend!r} "
        "(expected 'anthropic', 'openai', or 'none')."
    )
