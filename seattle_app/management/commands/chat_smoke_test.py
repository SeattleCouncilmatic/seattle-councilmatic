"""Run a single chatbot turn against the live Anthropic API + dev DB.

Sanity-checks the full chat tool-use loop end-to-end without standing
up the HTTP endpoint or the frontend. Use this to validate model +
tool behavior against your data before any user-facing surface is in
place.

Examples::

    python manage.py chat_smoke_test "what's the status of CB 120123?"
    python manage.py chat_smoke_test "recent housing bills"
    python manage.py chat_smoke_test "what does SMC 23.42.040 say?" --verbose
    python manage.py chat_smoke_test "compare CB-120000 and CB-120001" --model claude-sonnet-4-6

The command prints the final answer plus a usage summary (tokens,
estimated cost, tool calls made). With ``--verbose``, also prints each
tool call and its result.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from seattle_app.services.chat_service import run_chat_turn


class Command(BaseCommand):
    help = "Run a single chatbot turn against the dev DB and print the result."

    def add_arguments(self, parser):
        parser.add_argument(
            "question",
            help="The user's question — pass in quotes.",
        )
        parser.add_argument(
            "--model",
            default=None,
            help=f"Override CLAUDE_CHAT_MODEL ({settings.CLAUDE_CHAT_MODEL}).",
        )
        parser.add_argument(
            "--max-tool-calls",
            type=int,
            default=None,
            help=(
                f"Override CHAT_MAX_TOOL_CALLS_PER_TURN "
                f"({settings.CHAT_MAX_TOOL_CALLS_PER_TURN})."
            ),
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print each tool call's name, input, and result.",
        )

    def handle(self, *args, **opts):
        if not settings.ANTHROPIC_API_KEY:
            raise CommandError(
                "ANTHROPIC_API_KEY is empty. Set it in the environment before running."
            )

        question = opts["question"].strip()
        if not question:
            raise CommandError("question must not be empty")

        self.stdout.write(self.style.NOTICE(f"Question: {question}"))
        self.stdout.write(
            self.style.NOTICE(
                f"Default model: {settings.CLAUDE_CHAT_MODEL}  "
                f"Synthesis model: {settings.CLAUDE_CHAT_SYNTHESIS_MODEL}  "
                f"Max tool calls: "
                f"{opts['max_tool_calls'] or settings.CHAT_MAX_TOOL_CALLS_PER_TURN}"
            )
        )
        if opts["model"]:
            self.stdout.write(self.style.NOTICE(f"Override: {opts['model']}"))
        self.stdout.write("")

        result = run_chat_turn(
            history=[],
            user_message=question,
            model=opts["model"],
            max_tool_calls=opts["max_tool_calls"],
        )

        if opts["verbose"] and result.tool_calls:
            self.stdout.write(self.style.NOTICE("--- Tool calls ---"))
            for i, call in enumerate(result.tool_calls, 1):
                err = f" [error={call['error']}]" if call.get("error") else ""
                self.stdout.write(
                    f"  {i}. {call['name']}({json.dumps(call['input'], default=str)})"
                    f"{err}"
                )
                if call.get("result_keys"):
                    self.stdout.write(f"     → keys: {call['result_keys']}")
            self.stdout.write("")

        self.stdout.write(self.style.SUCCESS("--- Answer ---"))
        self.stdout.write(result.answer_text or "(empty answer)")
        self.stdout.write("")

        self.stdout.write(self.style.NOTICE("--- Usage ---"))
        self.stdout.write(f"  model:           {result.model_used}  ({result.model_reason})")
        self.stdout.write(f"  stop_reason:     {result.stop_reason}")
        self.stdout.write(f"  tool_calls:      {len(result.tool_calls)}")
        self.stdout.write(f"  input_tokens:    {result.input_tokens:,}")
        self.stdout.write(f"  cached_input:    {result.cached_input_tokens:,}")
        self.stdout.write(f"  output_tokens:   {result.output_tokens:,}")
        self.stdout.write(f"  estimated cost:  ${result.estimated_cost_usd}")
