"""HTTP endpoint for the civic-Q&A chatbot.

This is the Week 1 MVP: a single ``POST /api/chat/message`` endpoint
that accepts a conversation history + user message, runs one turn of
the tool-use loop, persists usage to ``ChatUsageLog``, and returns
the assistant's answer.

Week 2 will layer on top of this view: streaming SSE responses,
Cloudflare Turnstile validation, per-IP rate limiting via
``django-ratelimit``, and the per-conversation turn cap. The shape
below is intentionally minimal to keep that diff focused.

CSRF is exempted on this endpoint because the chat surface is
anonymous-only — there's no user session to forge against. Turnstile
in Week 2 is the meaningful abuse defense for this view.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db.models import Sum
from django.http import HttpResponseNotAllowed, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import ChatUsageLog
from .services import chat_service

logger = logging.getLogger(__name__)


def _client_ip(request) -> str:
    """Best-effort client IP, honoring X-Forwarded-For when present.

    In production this site sits behind Caddy, so REMOTE_ADDR is the
    proxy; X-Forwarded-For carries the real client IP.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _daily_spend_today() -> Decimal:
    """Sum of estimated_cost_usd for ChatUsageLog rows created today."""
    start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        ChatUsageLog.objects
        .filter(created_at__gte=start)
        .aggregate(s=Sum("estimated_cost_usd"))["s"]
    )
    return total or Decimal("0")


@csrf_exempt
def chat_message(request):
    """POST /api/chat/message

    Request body (JSON)::

        {
          "conversation_id": "<client-generated uuid>",
          "history":         [{"role": "user"|"assistant", "content": "..."} , ...],
          "user_message":    "what's the status of CB 120123?"
        }

    Response body::

        {
          "answer":           "...",
          "model":            "claude-haiku-4-5-...",
          "tool_calls":       [{"name": ..., "input": ...}, ...],
          "usage": {
            "input_tokens":         123,
            "cached_input_tokens":  4567,
            "output_tokens":        89,
            "estimated_cost_usd":   "0.012345"
          }
        }

    Returns 503 when today's aggregate estimated cost has crossed
    ``settings.CHAT_DAILY_DOLLAR_CAP``.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    if not settings.ANTHROPIC_API_KEY:
        return JsonResponse(
            {"error": "chat_not_configured", "detail": "ANTHROPIC_API_KEY is not set."},
            status=503,
        )

    # Hard kill-switch: daily $ cap.
    spent_today = _daily_spend_today()
    if spent_today >= Decimal(str(settings.CHAT_DAILY_DOLLAR_CAP)):
        return JsonResponse(
            {
                "error": "daily_cap_reached",
                "detail": "The chatbot has hit today's spend cap. Try again tomorrow.",
                "spent_today_usd": str(spent_today),
                "cap_usd": str(settings.CHAT_DAILY_DOLLAR_CAP),
            },
            status=503,
        )

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return JsonResponse(
            {"error": "bad_request", "detail": f"invalid JSON body: {exc}"},
            status=400,
        )

    user_message = (body.get("user_message") or "").strip()
    if not user_message:
        return JsonResponse(
            {"error": "bad_request", "detail": "user_message is required"},
            status=400,
        )
    if len(user_message) > 2000:
        return JsonResponse(
            {"error": "bad_request", "detail": "user_message exceeds 2000 chars"},
            status=400,
        )

    conversation_id = (body.get("conversation_id") or "")[:64]
    raw_history = body.get("history") or []
    if not isinstance(raw_history, list):
        return JsonResponse(
            {"error": "bad_request", "detail": "history must be a list"},
            status=400,
        )

    history: list[dict[str, Any]] = []
    for turn in raw_history[-12:]:  # last 6 user+assistant pairs
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = turn.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        history.append({"role": role, "content": content})

    try:
        result = chat_service.run_chat_turn(
            history=history,
            user_message=user_message,
        )
    except Exception:  # noqa: BLE001 - we want to log and 502
        logger.exception("chat_message: run_chat_turn failed")
        return JsonResponse(
            {"error": "upstream_error", "detail": "The chat service failed unexpectedly."},
            status=502,
        )

    ChatUsageLog.objects.create(
        conversation_id=conversation_id,
        ip_hash=chat_service.hash_ip(_client_ip(request)),
        model_used=result.model_used,
        input_tokens=result.input_tokens,
        cached_input_tokens=result.cached_input_tokens,
        output_tokens=result.output_tokens,
        tool_call_count=len(result.tool_calls),
        estimated_cost_usd=result.estimated_cost_usd,
    )

    return JsonResponse({
        "answer": result.answer_text,
        "model": result.model_used,
        "stop_reason": result.stop_reason,
        "tool_calls": [
            {"name": c["name"], "input": c.get("input"), "error": c.get("error")}
            for c in result.tool_calls
        ],
        "usage": {
            "input_tokens": result.input_tokens,
            "cached_input_tokens": result.cached_input_tokens,
            "output_tokens": result.output_tokens,
            "estimated_cost_usd": str(result.estimated_cost_usd),
        },
    })
