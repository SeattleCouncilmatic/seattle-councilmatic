"""Post-process pass to recover section titles that the parser truncated
when the heading wrapped onto a second line without a soft-hyphen.

Background
==========

``parse_smc_pdf.py``'s ``SECTION_RE`` matches one line: ``<num> <title>``.
When the SMC's section heading wraps without a trailing hyphen — e.g.

::

    23.47A.009 Standards applicable to specific
              areas
              A. Resolution of standards conflicts...

— the parser captures ``title="Standards applicable to specific"`` and
the leftover word ``"areas"`` becomes the first body line. ``title``
existing soft-hyphen fold logic (``parse_smc_pdf.py:973``) only fires
when the title ends in ``-``, so non-hyphenated wraps like this one
slip through.

Discovery scan (2026-05-08): 829 sections corpus-wide have a first body
line that looks like a title continuation (≤30 chars, no period, no
enumeration marker). Spans Title 1 through Title 25.

What this command does
======================

For each affected section:

1. Walk the first lines of ``full_text``. While each line looks like a
   title continuation (short, no period, no enumeration marker, no
   heading pattern, no leading lowercase number), pop it and append to
   ``title``. Keeps going for multi-line wraps (e.g.
   ``10.13.240 Quality standards for ground / meat and poultry, and
   ground / beef.``).
2. Apply ``clean_section_full_text.clean_text`` to the merged title to
   un-merge any pdfplumber word-merge artifacts ("Standardsapplicableto
   specific" → "Standards applicable to specific").
3. Save title and full_text.

Idempotent — sections whose first body line doesn't match the
continuation pattern are left alone.

Usage
=====

::

    python manage.py recover_truncated_titles                # full pass
    python manage.py recover_truncated_titles --dry-run      # report only
    python manage.py recover_truncated_titles --section 23.47A.009
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand

from seattle_app.management.commands.clean_section_full_text import clean_text
from seattle_app.models import MunicipalCodeSection


# Enumeration marker at line start: "A.", "B.", "1.", "a.", "i.", etc.
# Followed by whitespace. These start body subsections, not title
# continuations.
_ENUM_MARKER_RE = re.compile(r"^[A-Za-z0-9]{1,3}\.\s")
# Section number at line start ("23.47A.009 ..."). Defensive; shouldn't
# appear in a section's own full_text but the running-header strip in
# the parser occasionally leaves one in.
_SECTION_NUM_RE = re.compile(r"^\d+\.\d+[A-Z]?\.\d+[A-Z]?\b")
# Common heading patterns we don't want to absorb.
_HEADING_RE = re.compile(r"^(Chapter|Subchapter|Section|Title)\s+\d", re.IGNORECASE)

# Capitalized words that almost always start a body sentence rather than
# a title fragment. Articles, demonstratives, common subject openers,
# subordinating conjunctions, and frequent body-prose verb starters.
# Reject the line if its first word is one of these AND capitalized —
# real title fragments rarely start with these in capitalized form.
_BODY_FIRST_WORDS = frozenset({
    "the", "a", "an", "all", "any", "every", "each", "no", "none", "neither",
    "this", "that", "these", "those",
    "whenever", "when", "where", "while", "if", "unless", "until", "as",
    "because", "since", "though", "although", "before", "after",
    "for", "however", "therefore", "thus", "hence", "moreover", "additionally",
    "it", "they", "we", "you", "he", "she", "i",
    "there", "here", "such",
    "any", "every", "either", "neither", "both",
})

# Punctuation that signals a title ends mid-phrase and likely wraps.
# When the title's last char is one of these, we are MORE confident
# the next line is a title continuation. Em-dash / comma / open-paren /
# slash all suggest more content follows.
_TRUNCATION_PUNCT = frozenset({"—", "-", ",", "/", "("})

# Words that, when at the end of the title, strongly indicate the
# title was wrapped: prepositions, conjunctions, articles. A title
# rarely ends with one of these unless content follows.
_TRUNCATION_TRAILING_WORDS = frozenset({
    "of", "to", "in", "for", "on", "with", "by", "at", "from", "into", "onto",
    "off", "up", "down", "before", "after", "during", "since", "until",
    "through", "across", "against", "between", "beyond", "near", "over",
    "under", "without", "within", "via", "per", "about",
    "and", "or", "but", "yet", "nor",
    "the", "a", "an",
})


def _line_wraps(line: str) -> bool:
    """Does this line end mid-phrase (suggesting another wrap line
    follows)? Same shape as ``_title_looks_truncated`` but applied to
    each consumed continuation line so we stop greedy absorption."""
    s = line.rstrip()
    if not s:
        return False
    if s[-1] in _TRUNCATION_PUNCT:
        return True
    last_word = re.split(r"\s+", s)[-1].lower().strip(",.;:-—\"'")
    return last_word in _TRUNCATION_TRAILING_WORDS


def _title_looks_truncated(title: str) -> bool:
    """A title looks truncated if it ends with a truncation indicator —
    a comma / em-dash / slash / open-paren, or a preposition /
    conjunction / article. Otherwise we treat it as complete and skip
    the merge entirely."""
    t = title.rstrip()
    if not t:
        return False
    # Sentence-final punctuation → complete title, never merge.
    if t[-1] in ".!?":
        return False
    # Trailing punctuation that suggests wrap.
    if t[-1] in _TRUNCATION_PUNCT:
        return True
    # Trailing word check.
    last_word = re.split(r"\s+", t)[-1].lower().strip(",.;:-—")
    return last_word in _TRUNCATION_TRAILING_WORDS


def _looks_like_title_continuation(line: str) -> bool:
    """Heuristic: would this line plausibly continue a wrapped section
    title?

    * short (≤ 60 chars after strip)
    * not an enumeration marker (``A.``, ``1.``, ``a.``, etc.)
    * not a section / chapter / subchapter heading
    * doesn't end with sentence-final punctuation
    * first word isn't a capitalized body-prose opener (``The``, ``Any``,
      ``Whenever``, ...) — those almost always start body sentences.
    """
    s = line.strip()
    if not s:
        return False
    if len(s) > 60:
        return False
    if _ENUM_MARKER_RE.match(s):
        return False
    if _SECTION_NUM_RE.match(s):
        return False
    if _HEADING_RE.match(s):
        return False
    if s[-1] in ".;:":
        return False
    first_word = re.split(r"\s+", s)[0]
    if first_word and first_word[0].isupper() and first_word.lower() in _BODY_FIRST_WORDS:
        return False
    return True


def _recover(title: str, full_text: str) -> tuple[str, str, int]:
    """Return ``(new_title, new_full_text, lines_consumed)``. If the
    title doesn't look truncated, or if the first body line doesn't
    look like a continuation, returns the inputs unchanged with
    ``lines_consumed == 0``."""
    if not full_text:
        return title, full_text, 0
    lines = full_text.split("\n")
    if not lines or not _title_looks_truncated(title):
        # Title is "complete" (ends with terminator or content word)
        # AND the first body line isn't an obvious continuation. Skip
        # to avoid the false-positive class where body prose like
        # "The Director is authorized..." gets merged into a complete
        # title like "Rulemaking authority".
        first = lines[0].strip() if lines else ""
        if not first:
            return title, full_text, 0
        if not _looks_like_title_continuation(first):
            return title, full_text, 0
        # Tier 2 acceptance: title doesn't show a truncation marker but
        # the next line is short (≤ 30 chars) and lowercase-starting —
        # the 23.47A.009 case ("Standards applicable to specific" +
        # "areas"). Single short lowercase word is overwhelmingly a
        # title-continuation signature.
        if len(first) > 30:
            return title, full_text, 0
        if not first[0].islower():
            return title, full_text, 0
    extra: list[str] = []
    consumed = 0
    for line in lines:
        if not _looks_like_title_continuation(line):
            break
        extra.append(line.strip())
        consumed += 1
        # Stop greedy multi-line accumulation: as soon as we add a line
        # that itself doesn't wrap (no truncation marker at end), the
        # title is complete. Otherwise body prose with no enumeration
        # markers (1.01.040: "met / In accordance with RCW... /
        # adoption of the Seattle Municipal Code / by Ordinance...")
        # gets absorbed line by line.
        if not _line_wraps(line):
            break
    if not extra:
        return title, full_text, 0
    merged = (title.rstrip() + " " + " ".join(extra)).strip()
    cleaned = clean_text(merged)
    new_full_text = "\n".join(lines[consumed:]).lstrip("\n")
    return cleaned, new_full_text, consumed


class Command(BaseCommand):
    help = "Recover section titles that wrapped to a second line and got truncated."

    def add_arguments(self, parser):
        parser.add_argument(
            "--section",
            help="Process only this section number.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change; don't write to the DB.",
        )

    def handle(self, *args, **options):
        section_filter = options.get("section")
        dry = options["dry_run"]

        qs = MunicipalCodeSection.objects.exclude(full_text="").exclude(full_text__isnull=True)
        if section_filter:
            qs = qs.filter(section_number=section_filter)
        qs = qs.only("id", "section_number", "title", "full_text").order_by("section_number")

        scanned = 0
        changed = 0
        for s in qs:
            scanned += 1
            # Loop until convergence: each pass merges the next
            # continuation line if one is detected. Multi-line wraps
            # need multiple iterations because each iteration's
            # heuristics work off the *current* title; once the title
            # has absorbed one wrap line, the merged title may now
            # show a truncation marker that re-arms the next pass.
            new_title, new_full_text = s.title, s.full_text
            total_consumed = 0
            while True:
                t, ft, c = _recover(new_title, new_full_text)
                if c == 0:
                    break
                new_title, new_full_text = t, ft
                total_consumed += c
            if total_consumed == 0:
                continue
            self.stdout.write(
                f"  {s.section_number}: {s.title!r} + {total_consumed} line(s) -> {new_title!r}"
            )
            changed += 1
            if not dry:
                s.title = new_title
                s.full_text = new_full_text
                s.save(update_fields=["title", "full_text"])
        verb = "would update" if dry else "updated"
        self.stdout.write(self.style.SUCCESS(
            f"\nScanned {scanned} section(s); {verb} {changed}."
        ))
