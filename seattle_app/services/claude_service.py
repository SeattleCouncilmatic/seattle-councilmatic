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
    "  - Brief. 150 to 300 words for short or procedural sections; up to "
    "400 words for long substantive policy. Hard cap 400 words.\n"
    "  - Plain prose only. No markdown headers, bullet lists, or bold / "
    "italic formatting. The section number and title are displayed "
    "alongside your summary — do not repeat them.\n"
    "Write in second person ('you must', 'you can') for any rule that "
    "applies to a person; use third person only for procedural mechanics "
    "that don't require action from the reader. "
    "If the section is purely administrative (definitions, severability, "
    "scope of chapter), open by noting that it is administrative, then "
    "give the reader a navigation map: group what the section covers into "
    "a few functional categories (e.g. for a long definitions section, "
    "categories like \"people and businesses involved,\" \"how work is "
    "arranged,\" \"pay and time,\" \"agencies and officials,\" etc.) and "
    "name the terms or topics within each category. Do not explain what "
    "any individual term means. Aim for 150-300 words; small admin "
    "sections may be shorter."
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


BILL_TAG_VOCABULARY = (
    "Land Use & Zoning",
    "Public Safety",
    "Transportation",
    "Waterfront",
    "Seattle Center",
    "Housing",
    "Climate & Environment",
    "Budget & Taxes",
    "Labor",
    "Economic Development",
    "Civil Rights",
    "Health & Human Services",
    "Arts & Culture",
    "Parks & Public Spaces",
    "Utilities",
    "Education & Libraries",
    "Governance",
    "Elections",
    "Neighborhoods & Community",
    "Tribal Relations",
)


BILL_TAG_SYSTEM_PROMPT = (
    "You are a legislative analyst tagging Seattle City Council bills with "
    "issue-area labels. For each bill, choose 1 to 3 tags from this controlled "
    "vocabulary, ordered by relevance (most relevant first):\n\n"
    + "\n".join(f"  - {t}" for t in BILL_TAG_VOCABULARY)
    + "\n\nGuidance:\n"
    "  - Pick the *substantive* topic, not the procedural shell.\n"
    "  - 'Budget & Taxes' is reserved for bills that are *substantively "
    "about* budget allocation, taxation, levies, tax-increment financing, "
    "ballot measures to fund city programs, or fiscal policy. Do NOT add "
    "it as a secondary tag merely because money is involved as a mechanism "
    "for accomplishing the bill's actual topic. A contract authorization, "
    "routine appropriation tied to a specific program, fee or rate "
    "adjustment, or property surplus disposition takes the topic tag (e.g. "
    "'Utilities' for a water-rate adjustment; 'Transportation' for a "
    "streetcar funding ordinance; 'Seattle Center' for parking-charge "
    "amendments), not 'Budget & Taxes'. An ordinance appropriating money "
    "to pay claims for a given week IS 'Budget & Taxes'; a property-tax "
    "ballot proposition IS 'Budget & Taxes'.\n"
    "  - 'Utilities' covers Seattle City Light (electric) and Seattle Public "
    "Utilities (water/sewer/garbage/drainage). Bills authorizing City Light "
    "or SPU contracts, easements, or rate-setting are 'Utilities'.\n"
    "  - 'Land Use & Zoning' is the regulatory framework (zoning code, "
    "design review, permits). 'Housing' is housing supply, affordability, "
    "tenant protections, and homelessness prevention. A rezone enabling "
    "more multifamily housing is both.\n"
    "  - 'Health & Human Services' covers homelessness response, behavioral "
    "health, food assistance, and public health.\n"
    "  - 'Tribal Relations' is government-to-government work with sovereign "
    "tribal nations. Bills about Native Communities programs without a "
    "government-to-government angle are 'Civil Rights' or 'Health & Human "
    "Services' as appropriate.\n"
    "  - Be conservative on secondary tags. If a bill is squarely about one "
    "topic, return one tag. Two or three tags only when the bill genuinely "
    "spans them.\n"
    "  - Use only the exact vocabulary strings above; do not invent new tags."
)


BILL_TAG_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "description": (
                "1 to 3 issue-area tags from the controlled vocabulary, "
                "ordered by relevance (most relevant first). Cardinality "
                "is enforced via the system prompt and post-processing — "
                "Anthropic's schema validator rejects minItems/maxItems "
                "on array types."
            ),
            "items": {"type": "string", "enum": list(BILL_TAG_VOCABULARY)},
        },
    },
    "required": ["tags"],
    "additionalProperties": False,
}


REP_SUMMARY_SYSTEM_PROMPT = (
    "You are a non-partisan civic data communicator writing a short, "
    "neutral overview of a Seattle City Councilmember for residents who "
    "want to understand what their councilmember works on. You will "
    "receive a structured stats snapshot describing the member's seat, "
    "tenure, committee assignments, sponsorship portfolio (counts plus "
    "top issue areas plus a few notable bills), voting record, and a "
    "biographical paragraph block scraped from seattle.gov.\n\n"
    "Produce 2 to 3 short paragraphs of plain prose synthesizing the "
    "input. Hard cap 250 words. Constraints:\n"
    "  - Be neutral and factual. Do not speculate on political "
    "alignment, motivations, ideology, or how a member 'really' feels. "
    "Do not infer a member's party, faction, or coalition. Describe "
    "what they work on and how they vote — not why.\n"
    "  - Prefer the structured stats over the bio when they conflict. "
    "Bios are scraped from seattle.gov and may be stale (e.g. a member "
    "who returned to office after a prior term may have a bio that "
    "still describes them as retired). Trust the membership, "
    "sponsorship, and voting facts.\n"
    "  - Use the bio for background context only — career, education, "
    "community ties, prior public service. Do not use it for tenure "
    "claims or current activity.\n"
    "  - When tenure has a known start date, you may say 'serving since "
    "<year>' or 'in their first term since <year>'. When the start "
    "date is null, say 'currently serving' without inventing a date.\n"
    "  - Lead with the seat and current committee assignments. The "
    "second paragraph should describe the sponsorship portfolio "
    "(counts, top 2-3 issue areas, a representative sample). The third "
    "(optional) paragraph can cover voting record (yes-rate of active "
    "votes, notable dissents) and bio-derived background.\n"
    "  - When the issue-area breakdown is dominated by a single tag "
    "(e.g. >60% of primary sponsorships in one area), call that out as "
    "the member's primary focus area.\n"
    "  - 'Budget & Taxes' as a top tag often reflects the member's "
    "role on a finance/appropriations committee handling routine "
    "fiscal authorizations — frame it that way rather than implying "
    "tax policy is their personal focus area.\n"
    "  - Plain prose only. No markdown headers, bullets, or bold. "
    "The member's name and seat are displayed alongside your summary "
    "— do not repeat 'Councilmember <Name>' at the start.\n"
    "  - Do not editorialize about whether the member is effective, "
    "popular, controversial, or aligned with any other body. Stick to "
    "what they do.\n"
    "  - If the bio is empty (no seattle.gov About page exists), skip "
    "the background paragraph rather than padding the summary.\n"
    "  - Do not mention metadata about input availability in the prose "
    "(e.g. 'subject tags are unavailable', 'no biographical information "
    "from seattle.gov is available', 'no notable dissents are on record "
    "in the current dataset'). Degrade silently to whatever you can "
    "synthesize from the data you do have. Empty issue-area breakdowns "
    "should be handled by describing sponsorships from their titles "
    "alone; empty bios by simply omitting the background paragraph."
)


REP_SUMMARY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "2 to 3 paragraphs of plain prose summarizing the "
                "councilmember's seat, committees, sponsorship portfolio, "
                "voting record, and (when bio context exists) "
                "background. Paragraphs separated by '\\n\\n'. Hard "
                "cap 250 words; no markdown formatting."
            ),
        },
    },
    "required": ["summary"],
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
