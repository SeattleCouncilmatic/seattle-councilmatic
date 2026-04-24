"""Plain-English summaries of Seattle legislation and municipal code via Claude."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

import anthropic
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


SECTION_SYSTEM_PROMPT = (
    "You are a legal writer explaining sections of the Seattle Municipal Code "
    "to residents with no legal training. Your summaries must be:\n"
    "  - Accurate. Do not add rules that are not in the text.\n"
    "  - Concrete. Use everyday language and concrete examples where useful.\n"
    "  - Neutral. Describe what the law does, not whether it is good or bad.\n"
    "  - Brief. One to three short paragraphs.\n"
    "Write in second person where natural ('you must...'). If the section is "
    "purely administrative (definitions, severability, etc.), say so in one sentence."
)


LEGISLATION_SYSTEM_PROMPT = (
    "You are a legislative analyst explaining Seattle City Council legislation "
    "to residents. For each piece of legislation you receive, produce:\n"
    "  - A plain-English summary of what the legislation does.\n"
    "  - An impact analysis of how it changes current rules or practice.\n"
    "  - A structured list of the key changes.\n"
    "Be accurate, concrete, and neutral. Do not speculate about political "
    "motivations. If affected sections of the Seattle Municipal Code are "
    "provided, reference them by section number when relevant."
)


LEGISLATION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "One- to three-paragraph plain-English description of what the "
                "legislation does."
            ),
        },
        "impact_analysis": {
            "type": "string",
            "description": (
                "Explanation of how this legislation changes current rules, "
                "practice, or municipal code. May be empty if purely procedural."
            ),
        },
        "key_changes": {
            "type": "array",
            "description": "Discrete substantive changes introduced by this legislation.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short label for the change (under 10 words).",
                    },
                    "description": {
                        "type": "string",
                        "description": "One- to two-sentence description of the change.",
                    },
                    "affected_section": {
                        "type": "string",
                        "description": (
                            "SMC section number this change modifies, or empty "
                            "string if not applicable."
                        ),
                    },
                },
                "required": ["title", "description", "affected_section"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "impact_analysis", "key_changes"],
    "additionalProperties": False,
}


@dataclass
class SectionContext:
    """Lightweight value object for LLM input (decouples service from ORM)."""

    section_number: str
    title: str
    full_text: str


@dataclass
class LegislationAnalysis:
    summary: str
    impact_analysis: str
    key_changes: list = field(default_factory=list)
    model_version: str = ""


def _supports_adaptive_thinking(model: str) -> bool:
    # Haiku 4.5 does not support adaptive thinking or the effort parameter
    # and will 400 if either is sent. Opus and Sonnet 4.6+ support both.
    return "haiku" not in model.lower()


class ClaudeService:
    """Wrapper around the Anthropic SDK for Councilmatic summarization tasks."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or getattr(settings, "ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not configured. Set it in your environment "
                "or Django settings before instantiating ClaudeService."
            )
        self._client: Optional[anthropic.Anthropic] = None

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def summarize_code_section(
        self,
        section_number: str,
        title: str,
        full_text: str,
        model: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> tuple[str, str]:
        """Return (summary_text, model_used) for a single SMC section."""
        model = model or settings.CLAUDE_CODE_SECTION_MODEL
        user_content = (
            f"Section: SMC {section_number}\n"
            f"Title: {title}\n\n"
            f"Full text:\n{full_text}\n\n"
            "Write a plain-English summary of this section for a Seattle resident."
        )

        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": SECTION_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": user_content}],
        }
        if _supports_adaptive_thinking(model):
            kwargs["thinking"] = {"type": "adaptive"}

        response = self.client.messages.create(**kwargs)
        return self._extract_text(response), response.model

    def summarize_legislation(
        self,
        identifier: str,
        title: str,
        full_text: str,
        affected_sections: Optional[Iterable[SectionContext]] = None,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> LegislationAnalysis:
        """Return a structured analysis of a bill or ordinance."""
        model = model or settings.CLAUDE_LEGISLATION_MODEL
        sections_block = self._format_sections(affected_sections)

        user_content = (
            f"Legislation: {identifier}\n"
            f"Title: {title}\n\n"
            f"{sections_block}"
            f"Full text of the legislation:\n{full_text}"
        )

        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": LEGISLATION_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": user_content}],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": LEGISLATION_OUTPUT_SCHEMA,
                }
            },
        }
        if _supports_adaptive_thinking(model):
            kwargs["thinking"] = {"type": "adaptive"}

        response = self.client.messages.create(**kwargs)

        text = self._extract_text(response)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.exception(
                "Claude returned non-JSON output for legislation %s", identifier
            )
            raise

        return LegislationAnalysis(
            summary=data["summary"],
            impact_analysis=data.get("impact_analysis", ""),
            key_changes=data.get("key_changes", []),
            model_version=response.model,
        )

    def generate_and_save_section_summary(
        self,
        section,
        model: Optional[str] = None,
    ) -> str:
        """Summarize a MunicipalCodeSection and persist to its LLM fields."""
        summary_text, model_used = self.summarize_code_section(
            section_number=section.section_number,
            title=section.title,
            full_text=section.full_text,
            model=model,
        )
        section.plain_summary = summary_text
        section.summary_model = model_used
        section.summary_generated_at = timezone.now()
        section.save(
            update_fields=["plain_summary", "summary_model", "summary_generated_at"]
        )
        return summary_text

    @transaction.atomic
    def generate_and_save_legislation_summary(
        self,
        bill,
        affected_sections: Optional[Iterable] = None,
        model: Optional[str] = None,
    ):
        """Summarize a Bill and upsert its LegislationSummary record.

        `affected_sections` is an iterable of MunicipalCodeSection instances;
        they are passed as LLM context AND stored on the summary's M2M.
        """
        from seattle_app.models import LegislationSummary

        sections = list(affected_sections or [])
        section_contexts = [
            SectionContext(
                section_number=s.section_number,
                title=s.title,
                full_text=s.full_text,
            )
            for s in sections
        ]

        analysis = self.summarize_legislation(
            identifier=bill.identifier,
            title=getattr(bill, "title", "") or "",
            full_text=self._bill_text(bill),
            affected_sections=section_contexts,
            model=model,
        )

        summary, _ = LegislationSummary.objects.update_or_create(
            bill=bill,
            defaults={
                "summary": analysis.summary,
                "impact_analysis": analysis.impact_analysis,
                "key_changes": analysis.key_changes,
                "model_version": analysis.model_version,
            },
        )
        summary.affected_sections.set(sections)
        return summary

    @staticmethod
    def _extract_text(response) -> str:
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    @staticmethod
    def _bill_text(bill) -> str:
        """Best-effort pull of the bill's full text from the OCD Bill model."""
        # OCD Bill stores versions with links; the most recent version's text
        # is usually what callers want. Fall back to the abstract/title.
        for attr in ("full_text", "text"):
            value = getattr(bill, attr, None)
            if value:
                return value
        abstract = getattr(bill, "abstract", "") or ""
        return abstract or (getattr(bill, "title", "") or "")

    @staticmethod
    def _format_sections(sections: Optional[Iterable[SectionContext]]) -> str:
        if not sections:
            return ""
        parts = ["Relevant Seattle Municipal Code sections for reference:\n"]
        for section in sections:
            parts.append(
                f"--- SMC {section.section_number}: {section.title} ---\n"
                f"{section.full_text}\n"
            )
        parts.append("\n")
        return "\n".join(parts)
