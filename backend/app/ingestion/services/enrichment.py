"""V25.7 - Automatic detail enrichment for ingested government jobs.

This module:
1. Opens the official notification URL.
2. Extracts text from PDF / HTML.
3. Extracts recruitment details using regex.
4. Uses Gemini AI for fields that regex cannot reliably extract.
5. Never overwrites values already supplied by the collector.
6. Keeps jobs in review; nothing is auto-published.
"""

from __future__ import annotations

import io
import ipaddress
import json
import logging
import re
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("careeros.ingestion.enrichment")

PLACEHOLDER = "see official notification"

# Maximum amount of extracted text retained.
MAX_TEXT_CHARS = 250_000

# Gemini receives a large enough section of the notification.
AI_MAX_TEXT_CHARS = 80_000


# ==========================================================================
# DATE PARSING
# ==========================================================================

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_MONTH_RE = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)"
)

_DATE_PATTERNS = [
    (
        re.compile(
            r"\b(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})\b"
        ),
        "dmy_num",
    ),
    (
        re.compile(
            rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-]+"
            rf"({_MONTH_RE})\.?,?[\s\-]+(\d{{4}})\b",
            re.I,
        ),
        "dmy_txt",
    ),
    (
        re.compile(
            rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})"
            rf"(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
            re.I,
        ),
        "mdy_txt",
    ),
]


def _mk_date(y: int, m: int, d: int) -> date | None:
    try:
        if not (2000 <= y <= 2100):
            return None
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(fragment: str) -> list[date]:
    """Return all recognisable dates in order of appearance."""

    hits: list[tuple[int, date]] = []

    for pattern, kind in _DATE_PATTERNS:
        for match in pattern.finditer(fragment):

            if kind == "dmy_num":
                parsed = _mk_date(
                    int(match.group(3)),
                    int(match.group(2)),
                    int(match.group(1)),
                )

            elif kind == "dmy_txt":
                parsed = _mk_date(
                    int(match.group(3)),
                    _MONTHS[match.group(2).lower()[:3]],
                    int(match.group(1)),
                )

            else:
                parsed = _mk_date(
                    int(match.group(3)),
                    _MONTHS[match.group(1).lower()[:3]],
                    int(match.group(2)),
                )

            if parsed:
                hits.append((match.start(), parsed))

    hits.sort(key=lambda item: item[0])

    return [item[1] for item in hits]


def _date_after_label(
    text: str,
    label_patterns: list[str],
    window: int = 200,
    pick: str = "first",
) -> date | None:
    """Find a date immediately after a matching label."""

    for pattern in label_patterns:

        for match in re.finditer(pattern, text, re.I):

            rest = text[match.end(): match.end() + window]

            lines = rest.split("\n")

            first_line = find_dates(lines[0])

            if first_line:
                found = first_line

            elif len(lines) > 1 and not lines[0].strip(" :-–"):
                found = find_dates(lines[1])

            else:
                found = []

            if found:
                return (
                    found[0]
                    if pick == "first"
                    else found[-1]
                )

    return None


# ==========================================================================
# GENERAL TEXT HELPERS
# ==========================================================================

def _clean(
    value: str | None,
    maxlen: int,
) -> str | None:

    if not value:
        return None

    value = re.sub(r"\s+", " ", value)

    value = (
        value
        .strip()
        .lstrip(":-–— ")
        .strip()
    )

    if not value:
        return None

    return value[:maxlen]


def _grab(
    text: str,
    patterns: list[str],
    maxlen: int = 300,
    join_next_line: bool = True,
) -> str | None:
    """
    Extract text after a labelled field.

    Handles:
    - value on same line
    - value on next line
    - PDF/OCR layouts
    - accidental date/code fragments
    """

    def valid_candidate(value: str) -> bool:
        value = value.strip()

        if not value or len(value) < 3:
            return False

        if "?" in value:
            return False

        if re.fullmatch(
            r"[\(\[]?\s*\d{1,2}\s*[-/]\s*\d{4}"
            r"\s*[\)\]:;.,]?",
            value,
        ):
            return False

        if re.fullmatch(r"[\d\s\-/:().]+", value):
            return False

        return True

    for pattern in patterns:

        for match in re.finditer(pattern, text, re.I):

            start = match.end()
            end = text.find("\n", start)

            line = text[
                start:
                end if end != -1 else len(text)
            ]

            candidate = line.strip()

            if valid_candidate(candidate):
                cleaned = _clean(candidate, maxlen)

                if cleaned and valid_candidate(cleaned):
                    return cleaned

            if join_next_line and end != -1:

                next_end = text.find(
                    "\n",
                    end + 1,
                )

                next_line = text[
                    end + 1:
                    next_end if next_end != -1 else len(text)
                ].strip()

                if valid_candidate(next_line):

                    if not re.match(
                        r"^[A-Za-z][\w ./()&'-]{2,45}"
                        r"\s*[:?-]\s*",
                        next_line,
                    ):
                        cleaned = _clean(
                            next_line,
                            maxlen,
                        )

                        if cleaned and valid_candidate(cleaned):
                            return cleaned

    return None

# ==========================================================================
# VACANCIES
# ==========================================================================

def _vacancies(text: str) -> int | None:
    # --------------------------------------------------------------
    # 1. Explicit total / grand total - highest priority
    # --------------------------------------------------------------
    priority_patterns = [
        r"\bgrand\s+total\b[^\d]{0,30}(\d[\d,]*)\b",
        r"\btotal\s+(?:no\.?\s+of\s+)?(?:vacanc(?:y|ies)|posts?|positions?)"
        r"[^\d]{0,30}(\d[\d,]*)\b",
        r"\b(?:total|grand\s+total)\b[^\d]{0,15}(\d[\d,]*)\b",
        r"\btotal\s+(?:of\s+)?(\d[\d,]*)\s+"
        r"(?:vacanc(?:y|ies)|posts?|positions?)\b",
    ]

    for pattern in priority_patterns:
        for match in re.finditer(pattern, text, re.I):
            try:
                number = int(match.group(1).replace(",", ""))
            except (ValueError, TypeError):
                continue

            if 1 <= number <= 1_000_000:
                return number

    # --------------------------------------------------------------
    # 2. Position-wise vacancies
    #    Example:
    #    No. of Position(s) 03 (Three)
    #    No. of Position(s) 05 (Five)
    # --------------------------------------------------------------
    position_pattern = (
        r"no\.?\s+of\s+position(?:\(s\))?"
        r"\s*[:\-–]?\s*(\d[\d,]*)"
    )

    position_matches = re.findall(position_pattern, text, re.I)

    if position_matches:
        total_positions = 0

        for value in position_matches:
            try:
                number = int(value.replace(",", ""))
            except (ValueError, TypeError):
                continue

            if 1 <= number <= 1_000_000:
                total_positions += number

        if total_positions > 0:
            return total_positions

    # --------------------------------------------------------------
    # 3. Fallback patterns
    # --------------------------------------------------------------

    # --------------------------------------------------------------
    # 2. Fallback patterns - only if explicit total wasn't found
    # --------------------------------------------------------------
    fallback_patterns = [
        r"\b(\d[\d,]*)\s+(?:vacanc(?:y|ies)|posts?|positions?)\b",
        r"\brecruitment\s+(?:of|for|to)\s+(\d[\d,]*)\b",
    ]

    for pattern in fallback_patterns:
        for match in re.finditer(pattern, text, re.I):
            try:
                number = int(match.group(1).replace(",", ""))
            except (ValueError, TypeError):
                continue

            if 1 <= number <= 1_000_000:
                return number

    return None


# ==========================================================================
# PAY / SALARY
# ==========================================================================

def _pay_level(text: str) -> str | None:

    match = re.search(
        r"\b(?:pay\s*level|level)"
        r"\s*[-–:]?\s*(\d{1,2})\b",
        text,
        re.I,
    )

    if match:
        return f"Level {match.group(1)}"

    match = re.search(
        r"\bpay\s*band"
        r"\s*[-–:]?\s*([^\n]{3,60})",
        text,
        re.I,
    )

    if match:
        return _clean(
            match.group(1),
            100,
        )

    return None


def _normalize_money(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    value = re.sub(r"\s*/\s*$", "/-", value)
    return value

def _salary(text: str) -> str | None:
    """Extract monetary salary/pay only from salary-related context."""
    lines = text.splitlines()
    # Captures a full pay RANGE (e.g. "Rs. 19,900-63,200"), not just the
    # first number in it -- a bare `\d[\d,]*` alone was truncating ranges
    # down to their lower bound.
    money = re.compile(
        r"(?:₹|Rs\.?|INR)\s*\d[\d,]*(?:\s*[-–]\s*\d[\d,]*)?(?:\s*/\s*-?)?",
        re.I,
    )
    context = re.compile(
        r"\b(?:salary|pay\s*scale|pay\s*band|pay\s*level|pay\s*matrix|"
        r"remuneration|emoluments?|fellowship|consolidated\s+pay|"
        r"per\s+month|monthly\s+(?:salary|pay)|scale\s+of\s+pay|pay\s+of)\b",
        re.I,
    )
    fee_context = re.compile(
        r"\b(?:fee|amount)\s+payable\b|\bapplication\s+fee\b|"
        r"\bexam(?:ination)?\s+fee\b",
        re.I,
    )

    amounts = []
    for i, line in enumerate(lines):
        if not context.search(line):
            continue
        if fee_context.search(line):
            continue
        block = " ".join(x.strip() for x in lines[i:i + 4] if x.strip())
        # Don't let a salary context line bleed into a following fee
        # paragraph and pick up the fee amount instead.
        fee_hit = fee_context.search(block)
        if fee_hit:
            block = block[: fee_hit.start()]
        for m in money.finditer(block):
            value = re.sub(r"\s*/\s*-?$", "/-", m.group(0).strip())
            norm = re.sub(r"\s+", "", value).lower()
            if not any(re.sub(r"\s+", "", old).lower() == norm for old in amounts):
                amounts.append(value)

    if amounts:
        return " | ".join(amounts)

    for m in re.finditer(
        r"\b(?:pay\s*level|pay\s*scale|pay\s*matrix|scale\s+of\s+pay)\b"
        r"[^\n]{0,150}",
        text, re.I):
        found = money.findall(m.group(0))
        if found:
            return " | ".join(dict.fromkeys(
                re.sub(r"\s*/\s*-?$", "/-", x.strip()) for x in found))
    return None


# ==========================================================================
# ADVERTISEMENT NUMBER
# ==========================================================================

def _ad_number(text: str) -> str | None:

    patterns = [

        (
            r"(?:advertisement|advt\.?|advertisment)"
            r"\s*(?:no\.?|number)"
            r"\s*[:\-–.]?\s*"
            r"([A-Za-z0-9][A-Za-z0-9/\-\. ]{2,38})"
        ),

        (
            r"(?:notification|employment\s+notice|cen)"
            r"\s*(?:no\.?|number)"
            r"\s*[:\-–.]?\s*"
            r"([A-Za-z0-9][A-Za-z0-9/\-\. ]{2,38})"
        ),

        (
            r"\bCEN\s*[-/]?"
            r"(\d{1,3}\s*/\s*\d{4})"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if not match:
            continue

        value = re.split(
            r"\s{2,}|\n|\bdated\b|\bfor\b",
            match.group(1),
            flags=re.I,
        )[0]

        value = _clean(
            value,
            120,
        )

        if value and re.search(r"\d", value):
            return value

    return None


# ==========================================================================
# REGEX FIELD EXTRACTION
# ==========================================================================


# ============================================================================
# GENERIC ORGANISATION / LETTERHEAD BOILERPLATE
# ============================================================================

# Generic (non-SSC-specific) markers of organisation names / letterhead text.
# Used to strip page-header fragments that pypdf/OCR sometimes merges onto
# the same line as real body text across a page break, e.g.:
#   "Public Distribution, Staff Selection Commission and Ministry of
#    Culture: 12th Standard pass in Science stream ..."
# This applies to ANY recruiting body (SSC, UPSC, ISRO, DRDO, Railways,
# IBPS, state PSCs, universities, etc.) -- it matches generic organisation
# nouns, not any specific commission's name.
_ORG_BOILERPLATE_RE = re.compile(
    r"\b(?:government\s+of\s+india|ministry\s+of\s+[a-z&\s]{2,40}|"
    r"department\s+of\s+[a-z&\s]{2,40}|staff\s+selection\s+commission|"
    r"union\s+public\s+service\s+commission|public\s+service\s+commission|"
    r"public\s+distribution|recruitment\s+board|selection\s+board|"
    r"[a-z\s]+\bcorporation\b|[a-z\s]+\bauthority\b|[a-z\s]+\bcouncil\b|"
    r"[a-z\s]+\buniversity\s+service\s+commission\b)\b",
    re.I,
)

# Junk that should never be treated as extracted content regardless of field.
_URL_EMAIL_RE = re.compile(
    r"(https?://|www\.[a-z0-9-]+\.[a-z]{2,}|[\w.+-]+@[\w-]+\.[a-z]{2,}|"
    r"\bpage\s+\d+\s+of\s+\d+\b)",
    re.I,
)


# ==========================================================================
# SELECTION_PROCESS VALIDATION -- single source of truth
# ==========================================================================
#
# selection_process is uniquely prone to false positives: government
# notifications routinely place answer-key / normalisation / objection
# text, examination-scheme (paper pattern) text, and fee/age-relaxation
# text physically close to a selection-sounding heading, and all of it
# shares exam vocabulary ("examination", "marks", "test", "merit").
#
# This validator is deliberately the ONLY place that decides whether a
# selection_process string is acceptable, and it is applied to every
# candidate regardless of where it came from: the deterministic
# section-boundary extractor below, the AI (Gemini) fallback, AND a
# pre-existing stored value being re-checked during backfill. A candidate
# is accepted only if it names an actual selection mechanism and contains
# none of the markers of an unrelated section. This is a validation gate,
# not a search strategy -- it never searches the document itself.
_SELECTION_REJECT_RE = re.compile(
    r"\b(?:answer\s*keys?|tentative\s+answer|final\s+answer|"
    r"normali[sz](?:ed|ation)|representations?\b|objections?\b|"
    r"per\s+question|ex-?servicemen|age\s+relaxation|"
    r"relaxation\s+in\s+age|educational\s+qualifications?|"
    r"essential\s+qualifications?|application\s+fee|"
    r"fee\s+payable|reservation\s+of\s+vacanc\w*|"
    r"\bnationality\b|\bcertificate\b|\bundertaking\b|"
    r"general\s+instructions?|important\s+instructions?|"
    r"negative\s+marking|\bsyllabus\b)\b",
    re.I,
)

_SELECTION_MECHANISM_RE = re.compile(
    r"\b(?:computer\s+based\s+test|\bcbt\b|"
    r"written\s+(?:test|examination|exam)|skill\s+test|"
    r"typing\s+test|physical\s+(?:efficiency|standard)\s+test|"
    r"\bpet\b|\bpst\b|document(?:ary)?\s+verification|\bdv\b|"
    r"\binterviews?\b|personality\s+test|"
    r"tier[\s\-]*[iv]+|phase[\s\-]*[iv]+|"
    r"preliminary\s+exam(?:ination)?|main\s+exam(?:ination)?|"
    r"shortlist(?:ed|ing)?|merit\s+list|merit[\s\-]*based|"
    r"medical\s+examination|"
    r"multiple\s+choice|descriptive\s+(?:test|paper)|"
    r"candidates?\s+(?:will\s+be|are)\s+selected|"
    r"selection\s+(?:will\s+be|is)\s+based\s+on)\b",
    re.I,
)


def _valid_selection_process(value) -> bool:
    """Return True only if `value` is an acceptable selection_process
    string. Used for the regex extractor's own result, the AI fallback's
    result, AND a pre-existing DB value being re-validated during
    backfill -- so a bad value cannot survive through any path."""

    if not value:
        return False

    value = str(value).strip()

    if len(value) < 12:
        return False

    if "�" in value or "ï¿½" in value:
        return False

    if value.lower() == PLACEHOLDER:
        return False

    if _URL_EMAIL_RE.search(value):
        return False

    # Unrelated-section markers (answer key, normalisation, fee, age
    # relaxation, etc.) disqualify the candidate outright, even if it
    # also happens to contain exam vocabulary.
    if _SELECTION_REJECT_RE.search(value):
        return False

    # Must actually name a selection mechanism/stage -- generic words
    # like "examination" or "marks" alone are not sufficient.
    if not _SELECTION_MECHANISM_RE.search(value):
        return False

    devanagari = len(re.findall(r"[\u0900-\u097F]", value))
    latin_words = len(re.findall(r"\b[A-Za-z]{3,}\b", value))

    if devanagari >= 5 and latin_words < 4:
        return False

    return True


def _strip_boilerplate_prefix(line: str) -> str:
    """Remove a leading organisation/letterhead fragment that has been
    merged onto the same physical line as real body text (a common PDF
    text-extraction artifact at page breaks). Only strips a ':'-terminated
    prefix that itself contains generic organisation wording and no
    education-related terms, so real "Qualification: ..." style labels
    (already consumed by the heading match) and legitimate content are
    left untouched.
    """

    match = re.match(r"^(.{3,140}?):\s*(.+)$", line)

    if not match:
        return line

    prefix, rest = match.group(1), match.group(2)

    edu_kw = re.compile(
        r"\b(?:10th|12th|degree|diploma|graduate|bachelor|master|"
        r"engineering|science|qualification)\b",
        re.I,
    )

    if edu_kw.search(prefix):
        return line

    if _ORG_BOILERPLATE_RE.search(prefix):
        return rest

    return line


def _smart_field(text: str, field: str) -> str | None:
    """Generic context-aware extraction for government recruitment notices."""
    def clean(v: str) -> str:
        return re.sub(r"\s+", " ", v or "").strip(" :-–—")

    def major(line: str) -> bool:
        return bool(re.match(r"^\s*\d{1,3}\.\s+\S", line))

    def subsection(line: str) -> bool:
        return bool(re.match(r"^\s*\d{1,3}\.\d+(?:\.\d+)*\s+", line))

    if field == "qualification":
        heading = re.compile(
            r"(?:essential\s+educational\s+qualifications?|"
            r"minimum\s+educational\s+qualifications?|"
            r"educational\s+qualifications?|essential\s+qualifications?)"
            r"[^\n:]{0,100}:?", re.I)
        edu = re.compile(
            r"\b(?:10th|12th|intermediate|matric|diploma|degree|graduate|"
            r"graduation|postgraduate|post\s*graduate|b\.?\s*e\.?|b\.?\s*tech|"
            r"m\.?\s*e\.?|m\.?\s*tech|b\.?\s*sc|m\.?\s*sc|bachelor|master|"
            r"engineering|technology|science|university|board|equivalent|"
            r"recognized|recognised|qualification)\b", re.I)

        # Matches a post-wise sub-heading such as "8.1 For Data Entry
        # Operator (DEO) in ...:" so labelled qualifications can be kept
        # separate instead of collapsed into one sentence.
        label_re = re.compile(
            r"^\d{1,3}\.\d+(?:\.\d+)*\s+(?:for\s+)?(.{2,90}?)\s*[:\-–]\s*(.*)$",
            re.I,
        )

        for h in heading.finditer(text):
            segments: list[tuple[str | None, str]] = []
            current_label: str | None = None
            current_text: list[str] = []
            subs = 0

            def _flush():
                nonlocal current_text
                joined = clean(" ".join(current_text))
                if joined:
                    segments.append((current_label, joined))
                current_text = []

            for raw in text[h.end():].splitlines()[:80]:
                line = clean(raw)
                if not line:
                    continue
                if major(line):
                    break

                if subsection(line):
                    subs += 1
                    if subs > 10:
                        break
                    _flush()
                    # `clean()` strips a trailing ":" (needed elsewhere to
                    # tidy values), which would hide the very separator
                    # label_re needs. Re-normalise whitespace only, keeping
                    # the colon, so post-wise labels like "8.1 For DEO:"
                    # are recognised.
                    line_for_label = re.sub(r"\s+", " ", raw or "").strip()
                    lm = label_re.match(line_for_label)
                    if lm:
                        current_label = clean(lm.group(1))
                        remainder = _strip_boilerplate_prefix(
                            clean(lm.group(2))
                        )
                        if remainder and edu.search(remainder):
                            current_text.append(remainder)
                    else:
                        current_label = None
                    continue

                # Only treat this as a section boundary if the keyword
                # actually STARTS the line (i.e. looks like a heading of
                # its own), not merely appears inside a sentence -- e.g. a
                # qualification clause that cross-references "age
                # relaxation" rules for reserved categories must not be
                # mistaken for the start of the Age Limit section.
                if re.match(
                    r"^(?:age\s+limit|age\s+relaxation|application\s+fee|"
                    r"fee\s+payable|salary|pay\s*scale|pay\s*level|"
                    r"selection\s+process|important\s+dates?|"
                    r"how\s+to\s+apply|online\s+application)\b",
                    line, re.I):
                    if current_text or segments:
                        break
                    continue

                line = _strip_boilerplate_prefix(line)

                if edu.search(line):
                    current_text.append(line)

                if len(clean(" ".join(current_text))) >= 700:
                    _flush()

            _flush()

            if not segments:
                continue

            if len(segments) == 1 and not segments[0][0]:
                value = segments[0][1]
            else:
                value = " | ".join(
                    f"For {label}: {txt}" if label else txt
                    for label, txt in segments
                    if txt
                )

            value = re.split(
                r"\b(?:para\s+\d+(?:\.\d+)?\s+above|"
                r"department\s+of\s+personnel|government\s+of\s+india)\b",
                value, maxsplit=1, flags=re.I)[0].strip(" :-–—|")

            if _URL_EMAIL_RE.search(value):
                continue

            if len(value) >= 10:
                return value[:1200]
        return None

    if field == "age_limit":
        heading = re.compile(
            r"(?:age\s+limit|maximum\s+age|upper\s+age)[^\n:]{0,100}:?", re.I)
        for h in heading.finditer(text):
            tail = text[h.end():h.end() + 3000]
            m = re.search(r"\b\d{1,3}\s*[-–—]\s*\d{1,3}\s*years?\b",
                          tail, re.I)
            if m:
                return clean(m.group(0))
            m = re.search(
                r"\b(?:maximum|upper)\s+age\b[^\n]{0,120}?"
                r"\b\d{1,3}\s*years?\b", tail, re.I)
            if m:
                return clean(m.group(0))
        return None

    if field == "application_fee":
        money = re.compile(
            r"(?:₹|Rs\.?|INR)\s*\d[\d,]*(?:\s*/\s*-?)?", re.I)
        salary_context = re.compile(
            r"\b(?:salary|pay\s*scale|pay\s*level|pay\s*matrix|"
            r"remuneration|emoluments?)\b", re.I)
        patterns = [
            r"fee\s+payable", r"application\s+fee",
            r"examination\s+fee", r"exam(?:ination)?\s+fee", r"\bfee\b"
        ]
        for pattern in patterns:
            for m in re.finditer(pattern, text, re.I):
                tail = text[m.end():m.end() + 700]
                tail = re.split(r"\n\s*\d{1,3}\.\s+\S", tail, maxsplit=1)[0]
                # Don't let the fee search window bleed into a following
                # salary/pay paragraph and pick up a pay figure instead.
                sal_hit = salary_context.search(tail)
                if sal_hit:
                    tail = tail[: sal_hit.start()]
                found = money.search(tail)
                if found:
                    return re.sub(r"\s*/\s*-?$", "/-", clean(found.group(0)))
                free = re.search(r"\b(?:nil|no\s+fee|free)\b", tail, re.I)
                if free:
                    return clean(free.group(0))
        return None

    if field == "selection_process":
        # --------------------------------------------------------------
        # V25.8 redesign.
        #
        # The old version accepted ANY text window following a loosely
        # matched heading (including "Examination Scheme") as long as it
        # contained a handful of exam-flavoured keywords. That let
        # unrelated paragraphs -- answer-key procedure, normalisation,
        # objections/representations -- through, because those paragraphs
        # also mention "examination", "marks", "merit", etc.
        #
        # This version is section-structure-first and keyword-last:
        #   1. Only start from an explicit, line-anchored selection
        #      heading (not "Examination Scheme" alone).
        #   2. Walk the section using numbering structure (X, X.1, X.2 ...)
        #      and stop at the next MAJOR section or any other named
        #      section heading -- never a generic line-count window.
        #   3. Reject the whole section outright if it contains strong
        #      markers of an unrelated section (answer key, normalisation,
        #      objections, fee, age relaxation, qualification, etc.),
        #      even if it also contains exam words.
        #   4. Only accept the result if it actually describes a
        #      selection MECHANISM (a stage name or a "how selected"
        #      verb), not just incidental exam vocabulary.
        #   5. If no reliable selection section is found, fall back to a
        #      single explicit "candidates will be selected ..." style
        #      sentence; otherwise return None. A false value is worse
        #      than no value.
        # --------------------------------------------------------------

        # Line-anchored, explicit selection headings only. Deliberately
        # excludes "examination scheme" / "scheme of examination" --
        # those describe the exam PATTERN (paper structure, marks,
        # duration), not how candidates are selected, and conflating the
        # two is exactly what produced the answer-key false positive.
        heading = re.compile(
            r"^[ \t]*(?:\d{1,3}[.\)]\s*)?(?:"
            r"selection\s+(?:process|procedure|method|criteria)|"
            r"procedure\s+(?:of|for)\s+selection|"
            r"mode\s+of\s+selection|method\s+of\s+selection|"
            r"scheme\s+of\s+selection|"
            r"recruitment\s+process|"
            r"stages?\s+of\s+selection|"
            r"how\s+(?:will\s+)?candidates?\s+(?:will\s+)?be\s+selected"
            r")\b[^\n:]{0,80}:?[ \t]*$",
            re.I | re.M,
        )

        # Any other named section heading, line-anchored -- this is the
        # boundary that ends the selection section, whether or not it is
        # numbered as a "major" heading.
        other_heading = re.compile(
            r"^[ \t]*(?:\d{1,3}(?:\.\d+)*[.\)]\s*)?(?:"
            r"how\s+to\s+apply|application\s+fee|fee\s+payable|"
            r"age\s+limit|age\s+relaxation|relaxation\s+in\s+age|"
            r"eligibility|essential\s+qualifications?|"
            r"educational\s+qualifications?|nationality|reservation|"
            r"important\s+instructions?|general\s+instructions?|"
            r"important\s+dates?|documents?\s+required|"
            r"certificate|undertaking|medical\s+(?:standards?|fitness)|"
            r"salary|pay\s*scale|pay\s*level|"
            r"answer\s*keys?|tentative\s+answer|final\s+answer|"
            r"result\b|declaration\s+of\s+result|"
            r"marking\s+scheme|negative\s+marking|"
            r"examination\s+scheme|scheme\s+of\s+examination|"
            r"pattern\s+of\s+(?:the\s+)?examination|"
            r"syllabus|centres?\s+of\s+examination"
            r")\b",
            re.I,
        )

        # Acceptance of the final candidate is delegated entirely to the
        # module-level `_valid_selection_process`, so the regex extractor,
        # the AI fallback, and backfill's re-check of a stored value all
        # apply the exact same rule. This function does not itself search
        # for keywords -- it only walks the section found by `heading`.
        def _collect_section(start_pos: int) -> str | None:
            """Walk lines from start_pos until a genuine section
            boundary, keeping numbered sub-points as part of the same
            section rather than treating them as new sections."""

            collected: list[str] = []
            subs = 0

            for raw in text[start_pos:].splitlines()[:80]:
                line = clean(raw)

                if not line:
                    continue

                if major(line):
                    break

                if subsection(line):
                    subs += 1
                    if subs > 12:
                        break
                    # Strip the sub-numbering but keep the content as
                    # part of this section.
                    line = re.sub(
                        r"^\d{1,3}\.\d+(?:\.\d+)*\s*", "", line
                    )
                elif other_heading.match(line):
                    # A different named section has started -- stop.
                    break

                line = _strip_boilerplate_prefix(line)

                if len(re.findall(r"\b[A-Za-z]{3,}\b", line)) < 1:
                    continue

                collected.append(line)

                if len(clean(" ".join(collected))) >= 900:
                    break

            if not collected:
                return None

            return clean(" ".join(collected))

        for h in heading.finditer(text):
            value = _collect_section(h.end())

            if _valid_selection_process(value):
                return value[:1000]

        # ----------------------------------------------------------------
        # No reliable heading/section found. As a last resort, accept a
        # single explicit sentence that plainly states the mechanism --
        # still gated by the exact same validator. No heading, no section
        # walk, no generic window, no keyword search of the whole document.
        # ----------------------------------------------------------------
        sentence_re = re.compile(
            r"(?:candidates?\s+will\s+be\s+selected[^.\n]{0,300}\.|"
            r"selection\s+(?:will\s+be|is)\s+based\s+on[^.\n]{0,300}\.|"
            r"selection\s+will\s+comprise[^.\n]{0,300}\.)",
            re.I,
        )

        for m in sentence_re.finditer(text):
            value = clean(m.group(0))

            if _valid_selection_process(value):
                return value[:1000]

        return None

    return None

def extract_fields(text: str) -> dict:
    """
    Extract recruitment information using deterministic rules.
    """

    text = text[:MAX_TEXT_CHARS]

    result: dict = {}

    # ----------------------------------------------------------------------
    # Vacancies
    # ----------------------------------------------------------------------

    vacancies = _vacancies(text)

    if vacancies:
        result["vacancies"] = vacancies

    # ----------------------------------------------------------------------
    # Text fields
    # ----------------------------------------------------------------------

    extracted = {

        "qualification": _smart_field(
            text,
            "qualification",
        ),

        "age_limit": _smart_field(
            text,
            "age_limit",
        ),

        "age_relaxation": _grab(
            text,
            [
                r"age\s+relaxation"
                r"[^\n:\-–]{0,30}[:\-–]",

                r"relaxation\s+in\s+age"
                r"[^\n:\-–]{0,30}[:\-–]?",
            ],
            500,
        ),

        "application_fee": _smart_field(
            text,
            "application_fee",
        ),

        "selection_process": _smart_field(
            text,
            "selection_process",
        ),

        "location": _grab(
            text,
            [
                r"(?:place|location)"
                r"\s+of\s+(?:posting|work|job)"
                r"\s*[:\-–]",

                r"job\s+location"
                r"\s*[:\-–]",
            ],
            200,
            join_next_line=False,
        ),

        "pay_level": _pay_level(text),

        "salary": _salary(text),

        "ad_number": _ad_number(text),
    }


    

    # ----------------------------------------------------------------------
    # Generic field validation
    # ----------------------------------------------------------------------

    def _looks_like_date_fragment(value: str) -> bool:
        if not value:
            return False

        value = value.strip()

        # OCR/PDF fragments such as:
        # 10-2026), 08-2026):, 12/2026
        if re.fullmatch(
            r"[\(\[]?\s*\d{1,2}\s*[-/]\s*\d{4}\s*[\)\]:;.,]?",
            value,
            re.I,
        ):
            return True

        return False


    def _valid_extracted_value(key: str, value) -> bool:
        if value is None:
            return False

        value = str(value).strip()

        if not value or len(value) < 2:
            return False

        # Never accept obvious OCR replacement characters.
        if "ï¿½" in value:
            return False

        # Reject date-like fragments accidentally captured as
        # qualification/age/fee/etc.
        if _looks_like_date_fragment(value):
            return False

        # Qualification must contain meaningful educational language and
        # should not be a long mixture of unrelated administrative text.
        if key == "qualification":
            if re.fullmatch(r"[\d\s\-/:().]+", value):
                return False
            if not re.search(
                r"\b(?:10th|12th|degree|diploma|graduate|"
                r"bachelor|master|b\.?\s*tech|m\.?\s*tech|"
                r"b\.?\s*sc|m\.?\s*sc|engineering|science|"
                r"recognized|recognised|equivalent|board|university)\b",
                value,
                re.I,
            ):
                return False
            if _ORG_BOILERPLATE_RE.search(value) and len(value) > 300:
                return False
            if _URL_EMAIL_RE.search(value):
                return False

        # Age limit should actually contain an age-related number.
        if key == "age_limit":
            if not re.search(r"\b\d{1,3}\b", value):
                return False

            # Reject values that are clearly dates.
            if re.search(r"\b\d{1,2}[-/]\d{4}\b", value):
                return False

        # Fee should contain money/number/free/nil/no fee.
        if key == "application_fee":
            if not re.search(
                r"(₹|rs\.?|inr|\b\d[\d,]*\b|nil|no\s+fee|free)",
                value,
                re.I,
            ):
                return False

        # Salary should contain money, pay level, fellowship,
        # remuneration, consolidated pay, etc.
        if key == "salary":
            if not re.search(
                r"(₹|rs\.?|inr|salary|pay|fellowship|"
                r"remuneration|emolument|consolidated)",
                value,
                re.I,
            ):
                return False

        # Selection text should not be pure OCR garbage.
        if key == "selection_process":
            if _URL_EMAIL_RE.search(value):
                return False
            devanagari = len(
                re.findall(r"[\u0900-\u097F]", value)
            )

            latin_words = len(
                re.findall(r"\b[A-Za-z]{3,}\b", value)
            )

            if devanagari >= 5 and latin_words < 3:
                return False

            if len(value) < 8:
                return False

        return True


    # ----------------------------------------------------------------------
    # Apply generic validation
    # ----------------------------------------------------------------------

    for key, value in extracted.items():
        if _valid_extracted_value(key, value):
            result[key] = value


    # ----------------------------------------------------------------------
    # Validate selection process
    # ----------------------------------------------------------------------

    selection = result.get("selection_process")

    if selection:
        devanagari_count = len(
            re.findall(r"[\u0900-\u097F]", selection)
        )

        latin_words = len(
            re.findall(r"\b[A-Za-z]{3,}\b", selection)
        )

        replacement_chars = selection.count("ï¿½")

        # Remove OCR-garbled / Hindi-corrupted selection text.
        if (
            replacement_chars > 0
            or (devanagari_count >= 5 and latin_words < 4)
        ):
            result.pop("selection_process", None)


    # ----------------------------------------------------------------------
    # Application start date
    # ----------------------------------------------------------------------

    start_date = _date_after_label(
        text,
        [
            r"(?:online\s+)?"
            r"(?:application|registration)s?"
            r"\s+(?:starts?|begins?|opens?|"
            r"commences?|start\s+date)"
            r"\s*(?:on|from)?"
            r"[^\n\d]{0,30}",

            r"(?:start|opening|commencement)"
            r"\s+(?:date|of\s+(?:online\s+)?"
            r"(?:application|registration))"
            r"[^\n\d]{0,30}",

            r"date\s+of\s+(?:opening|start)"
            r"[^\n\d]{0,30}",
        ],
    )


    # ----------------------------------------------------------------------
    # Deadline
    # ----------------------------------------------------------------------

    deadline = _date_after_label(
        text,
        [
            r"last\s+date"
            r"\s+(?:for|of|to)\s*"
            r"(?:online\s+)?"
            r"(?:submission|receipt|apply(?:ing)?|"
            r"registration|application|filling)?"
            r"[^\n\d]{0,40}",

            r"last\s+date"
            r"[^\n\d]{0,30}",

            r"closing\s+date"
            r"[^\n\d]{0,30}",

            r"(?:apply|application)"
            r"\s+(?:on\s*line\s+)?"
            r"(?:till|before|upto|up\s+to)"
            r"[^\n\d]{0,20}",
        ],
        pick="first",
    )


    # ----------------------------------------------------------------------
    # Exam date
    # ----------------------------------------------------------------------

    exam_date = _date_after_label(
        text,
        [
            r"date\s+of\s+(?:the\s+)?"
            r"(?:tentative\s+)?"
            r"(?:computer\s+based\s+)?"
            r"(?:examination|exam|written\s+test|cbt)"
            r"[^\n\d]{0,30}",

            r"(?:tentative\s+)?"
            r"exam(?:ination)?\s+date"
            r"[^\n\d]{0,30}",

            r"(?:examination|exam|written\s+test)"
            r"\s+(?:will\s+be\s+held\s+)?"
            r"on\s*[:\-–]?\s*",

            # Multi-stage exams (SSC/UPSC/Railways/IBPS/etc. all use
            # "Tier"/"Phase"/"Preliminary"/"Main" style staging generically).
            r"tier[\s\-]*[iv]+\b[^\n\d]{0,40}",
            r"phase[\s\-]*[iv]+\b[^\n\d]{0,40}",
            r"preliminary\s+exam(?:ination)?[^\n\d]{0,30}",
            r"main\s+exam(?:ination)?[^\n\d]{0,30}",
            r"computer\s+based\s+(?:test|examination)\s*"
            r"(?:\(?cbt\)?)?[^\n\d]{0,30}",
        ],
    )


    if start_date:
        result["start_date"] = start_date

    if deadline:
        result["deadline"] = deadline

    if exam_date:
        result["exam_date"] = exam_date


    # ----------------------------------------------------------------------
    # Sanity check
    # ----------------------------------------------------------------------

    if start_date and deadline and deadline < start_date:
        result.pop("start_date", None)

    return result


# ==========================================================================
# URL SAFETY
# ==========================================================================

def _safe_url(url: str | None) -> bool:

    if not url:
        return False

    parsed = urlparse(url)

    if (
        parsed.scheme
        not in {"http", "https"}
        or not parsed.hostname
    ):
        return False

    host = parsed.hostname.lower()

    if (
        host == "localhost"
        or host.endswith(".local")
        or host.endswith(".internal")
    ):
        return False

    try:

        ip = ipaddress.ip_address(host)

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
        ):
            return False

    except ValueError:
        pass

    return True


def _same_site(
    a: str,
    b: str,
) -> bool:

    host_a = (
        urlparse(a).hostname or ""
    ).lower()

    host_b = (
        urlparse(b).hostname or ""
    ).lower()

    if not host_a or not host_b:
        return False

    def base(host: str) -> str:

        if host.endswith(
            (
                ".gov.in",
                ".nic.in",
                ".ac.in",
                ".co.in",
            )
        ):
            return ".".join(
                host.split(".")[-3:]
            )

        return ".".join(
            host.split(".")[-2:]
        )

    return base(host_a) == base(host_b)


# ==========================================================================
# PDF EXTRACTION
# ==========================================================================

def _pdf_text(data: bytes) -> str:

    try:

        from pypdf import PdfReader

        reader = PdfReader(
            io.BytesIO(data)
        )

        # Government notifications can be long.
        # Read up to 100 pages.
        pages = reader.pages[:100]

        extracted: list[str] = []

        for page in pages:

            try:

                page_text = (
                    page.extract_text()
                    or ""
                )

                if page_text.strip():
                    extracted.append(
                        page_text
                    )

            except Exception as exc:
                logger.info(
                    "PDF page extraction failed: %s",
                    exc,
                )

        return "\n".join(extracted)

    except Exception as exc:
        logger.info(
            "PDF text extraction failed: %s",
            exc,
        )

        return ""


# ==========================================================================
# HTML / PDF COLLECTION
# ==========================================================================

_PDF_LINK_HINT = re.compile(
    r"(notif|advert|advt|notice|recruit|"
    r"vacanc|cen|detailed|employment|short)",
    re.I,
)

_APPLY_HINT = re.compile(
    r"(apply\s*online|online\s*appl|"
    r"register\s*(?:here|now|online)|"
    r"apply\s*now|click\s*here\s*to\s*apply)",
    re.I,
)


def _collect_from_url(
    url: str,
    max_pdfs: int = 2,
) -> tuple[str, str | None, str | None]:
    """
    Return:

        combined_text
        apply_url
        pdf_url_used
    """

    from app.ingestion.collectors.http_client import fetch_bytes

    if not _safe_url(url):
        return "", None, None

    data = fetch_bytes(url, respect_robots=False)

    if not data:
        return "", None, None

    # ----------------------------------------------------------------------
    # Direct PDF
    # ----------------------------------------------------------------------

    if data[:5] == b"%PDF-":

        return (
            _pdf_text(data),
            None,
            url,
        )

    # ----------------------------------------------------------------------
    # HTML
    # ----------------------------------------------------------------------

    try:

        from bs4 import BeautifulSoup

        html = data.decode(
            "utf-8",
            errors="ignore",
        )

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        for tag in soup(
            [
                "script",
                "style",
                "noscript",
            ]
        ):
            tag.decompose()

        page_text = soup.get_text(
            "\n"
        )

        page_text = re.sub(
            r"[ \t]+",
            " ",
            page_text,
        )

        page_text = re.sub(
            r"\n\s*\n+",
            "\n",
            page_text,
        )

        apply_url = None

        pdf_links: list[str] = []

        # ------------------------------------------------------------------
        # Find links
        # ------------------------------------------------------------------

        for anchor in soup.select(
            "a[href]"
        ):

            href = urljoin(
                url,
                anchor.get("href", ""),
            )

            label = " ".join(
                anchor.stripped_strings
            )

            if not _safe_url(href):
                continue

            # Apply online
            if (
                apply_url is None
                and _APPLY_HINT.search(label)
            ):
                apply_url = href

            # Notification PDFs
            if (
                href.lower()
                .split("?")[0]
                .endswith(".pdf")
                and _same_site(url, href)
                and (
                    _PDF_LINK_HINT.search(label)
                    or _PDF_LINK_HINT.search(href)
                )
            ):
                pdf_links.append(href)

        combined = page_text

        used_pdf = None

        # ------------------------------------------------------------------
        # Download linked notification PDFs
        # ------------------------------------------------------------------

        for link in pdf_links[:max_pdfs]:

            blob = fetch_bytes(link, respect_robots=False)

            if (
                blob
                and blob[:5] == b"%PDF-"
            ):

                pdf_text = _pdf_text(
                    blob
                )

                if pdf_text.strip():

                    combined += (
                        "\n"
                        + pdf_text
                    )

                    used_pdf = (
                        used_pdf
                        or link
                    )

        return (
            combined,
            apply_url,
            used_pdf,
        )

    except Exception as exc:

        logger.info(
            "HTML parse failed for %s: %s",
            url,
            exc,
        )

        return "", None, None


# ==========================================================================
# GEMINI AI EXTRACTION
# ==========================================================================

_AI_KEYS = [
    "vacancies",
    "qualification",
    "age_limit",
    "age_relaxation",
    "application_fee",
    "salary",
    "pay_level",
    "selection_process",
    "ad_number",
    "location",
    "start_date",
    "deadline",
    "exam_date",
]


_AI_SYSTEM = """
You are a precise information-extraction engine for Indian government
recruitment notifications.

Extract ONLY information explicitly present in the supplied official
recruitment notification.

Return EXACTLY ONE valid JSON object.

Allowed schema:

{
  "vacancies": integer or null,
  "qualification": string or null,
  "age_limit": string or null,
  "age_relaxation": string or null,
  "application_fee": string or null,
  "salary": string or null,
  "pay_level": string or null,
  "selection_process": string or null,
  "ad_number": string or null,
  "location": string or null,
  "start_date": "YYYY-MM-DD" or null,
  "deadline": "YYYY-MM-DD" or null,
  "exam_date": "YYYY-MM-DD" or null
}

STRICT RULES:

1. Never guess.
2. Never infer missing information.
3. If information is not explicitly available, return null.
4. For vacancies, return the total number of posts when an explicit
   grand total is present.
5. If category-wise vacancies are present AND a grand total is explicitly
   stated, use the grand total.
6. Preserve qualification details such as degree, branch, percentage,
   subjects and experience.
7. Preserve minimum/maximum age information.
8. Preserve age relaxation information if explicitly stated.
9. Preserve salary, pay scale and pay level.
10. Preserve application fee.
11. Preserve selection process.
12. Do not confuse notification date with application start date.
13. Do not confuse application deadline with examination date.
14. Dates must be YYYY-MM-DD.
15. If the examination date is tentative, preserve "tentative" in the
    relevant textual field only when appropriate.
16. Do not create values from the job title.
17. Do not include explanations outside the JSON object.
18. selection_process must come ONLY from an explicit section describing
    how candidates are selected (e.g. "Selection Process", "Mode of
    Selection", "Recruitment Process") or an explicit sentence stating
    the selection mechanism (e.g. "Computer Based Test followed by Skill
    Test and Document Verification"). It must name actual stages
    (written exam / CBT / interview / skill test / document
    verification / shortlisting / merit list, etc.).
19. selection_process must NEVER be taken from: examination scheme or
    paper pattern text, marking/negative-marking rules, answer key or
    tentative/final answer key text, score normalisation text,
    representation/objection handling text, application fee text, age
    relaxation text, or general/important instructions. If the
    notification only has this kind of text and no explicit selection
    description, return null for selection_process -- do not guess or
    substitute nearby text.

Return JSON only.
""".strip()


def _extract_json_object(
    raw: str,
) -> dict:

    raw = raw.strip()

    # Remove markdown fences.
    raw = re.sub(
        r"^```(?:json)?\s*",
        "",
        raw,
        flags=re.I,
    )

    raw = re.sub(
        r"\s*```$",
        "",
        raw,
        flags=re.I,
    )

    raw = raw.strip()

    # Find JSON object if Gemini added extra text.
    start = raw.find("{")
    end = raw.rfind("}")

    if start == -1 or end == -1:
        raise ValueError(
            "Gemini did not return a JSON object"
        )

    raw = raw[
        start:
        end + 1
    ]

    return json.loads(raw)


def _ai_extract(
    db,
    text: str,
) -> dict:
    """
    Gemini fallback extraction.

    Regex extraction happens first.
    Gemini fills fields that regex cannot reliably identify.
    """

    from app.ai.completion_service import (
        generate,
    )

    # Give Gemini enough notification text.
    if isinstance(text, tuple):
        text = text[0]
    if not isinstance(text, str):
        text = str(text)

    snippet = text[
        :AI_MAX_TEXT_CHARS
    ]

    result = generate(
        db,
        operation="ingestion.enrich",
        system_prompt=_AI_SYSTEM,
        user_message=(
            "Extract the recruitment details "
            "from this official government "
            "notification:\n\n"
            + snippet
        ),
        provider="gemini",
        temperature=0.0,
        max_tokens=1800,
    )

    data = _extract_json_object(
        result.text
    )

    clean: dict = {}

    for key in _AI_KEYS:

        value = data.get(key)

        if value is None:
            continue

        if isinstance(value, str):

            value = value.strip()

            if value.lower() in {
                "",
                "null",
                "none",
                "not specified",
                "not mentioned",
                "n/a",
            }:
                continue

        # --------------------------------------------------------------
        # Vacancies
        # --------------------------------------------------------------

        if key == "vacancies":

            try:

                match = re.search(
                    r"\d[\d,]*",
                    str(value),
                )

                if not match:
                    continue

                number = int(
                    match.group(
                        0
                    ).replace(",", "")
                )

                if (
                    1
                    <= number
                    <= 1_000_000
                ):
                    clean[key] = number

            except (
                ValueError,
                TypeError,
            ):
                pass

        # --------------------------------------------------------------
        # Dates
        # --------------------------------------------------------------

        elif key in {
            "start_date",
            "deadline",
            "exam_date",
        }:

            try:

                date_value = (
                    str(value)
                    .strip()[:10]
                )

                parsed = datetime.strptime(
                    date_value,
                    "%Y-%m-%d",
                ).date()

                clean[key] = parsed

            except (
                ValueError,
                TypeError,
            ):
                pass

        # --------------------------------------------------------------
        # Text fields
        # --------------------------------------------------------------

        else:

            cleaned = _clean(
                str(value),
                1000,
            )

            # selection_process is validated here too (not just by the
            # caller) so _ai_extract can never hand back an answer-key /
            # exam-scheme paragraph on its own, regardless of how its
            # result is consumed.
            if key == "selection_process":
                if cleaned and _valid_selection_process(cleaned):
                    clean[key] = cleaned
            elif cleaned:
                clean[key] = cleaned

    return clean


# ==========================================================================
# RECORD HELPERS
# ==========================================================================

def _is_blank(
    value,
) -> bool:

    if value is None:
        return True

    if isinstance(
        value,
        str,
    ):

        value = (
            value
            .strip()
            .lower()
        )

        return (
            value == ""
            or value == PLACEHOLDER
            or value.startswith(
                "discovered from the official source"
            )
        )

    return False


# Important fields which trigger Gemini.
_IMPORTANT = (
    "vacancies",
    "qualification",
    "age_limit",
    "application_fee",
    "salary",
    "pay_level",
    "selection_process",
    "deadline",
    "exam_date",
)


# ==========================================================================
# PUBLIC ENRICHMENT API
# ==========================================================================

def enrich_record(
    record,
    db=None,
    force_replace: bool = False,
):
    """
    Fill missing government recruitment details.

    Order:

        Official notification
              v
        PDF / HTML extraction
              v
        Regex
              v
        Gemini for missing fields
              v
        JobRecord
    """

    from app.core.config import settings

    # Feature flag.
    if not getattr(
        settings,
        "ingestion_enrich_details",
        True,
    ):
        return record

    # Prefer notification URL.
    url = (
        record.notification_url
        or record.official_url
    )

    if not url:
        return record

    try:

        # --------------------------------------------------------------
        # Download official notification
        # --------------------------------------------------------------

        text, apply_url, pdf_url = (
            _collect_from_url(url)
        )

        if not text.strip():
            logger.info(
                "No notification text found for %s",
                url,
            )
            return record

        # --------------------------------------------------------------
        # Regex extraction
        # --------------------------------------------------------------

        found = extract_fields(
            text
        )

        # Remove stale salary values that were previously populated from an
        # unrelated money amount. A valid new salary must come from salary/pay
        # context or from AI fallback.
        if "salary" not in found:
            current_salary = getattr(record, "salary", None)
            current_fee = getattr(record, "application_fee", None)
            if (
                current_salary
                and current_fee
                and re.sub(r"\s+", "", str(current_salary)).lower()
                == re.sub(r"\s+", "", str(current_fee)).lower()
            ):
                found["salary"] = None

        logger.info(
            "Regex enrichment found fields=%s for %s",
            sorted(found.keys()),
            getattr(
                record,
                "title",
                "unknown",
            ),
        )

        # --------------------------------------------------------------
        # Gemini fallback
        # --------------------------------------------------------------

        ai_used = False

        ai_enabled = getattr(
            settings,
            "ingestion_ai_enrichment",
            False,
        )

        missing_important = any(
            key not in found
            for key in _IMPORTANT
        )

        if (
            db is not None
            and ai_enabled
            and missing_important
        ):

            try:

                ai_data = _ai_extract(
                    db,
                    text,
                )

                for key, value in ai_data.items():

                    # IMPORTANT:
                    # Never overwrite a deterministic result.
                    # Also reject obvious AI garbage before accepting fallback data.
                    if key in {"qualification", "age_limit", "application_fee",
                               "salary", "selection_process"}:
                        if not value:
                            continue
                        value_text = str(value).strip()
                        if "�" in value_text or "ï¿½" in value_text:
                            continue

                    # selection_process gets the same strict, non-negotiable
                    # validation as the deterministic extractor -- the AI
                    # fallback is just as capable of picking up an
                    # answer-key / exam-scheme paragraph as the old regex
                    # was, since it only sees raw document text. A rejected
                    # AI value is simply dropped, not substituted with
                    # anything else.
                    if key == "selection_process" and not _valid_selection_process(value):
                        continue

                    found.setdefault(
                        key,
                        value,
                    )

                ai_used = bool(
                    ai_data
                )

                logger.info(
                    "AI enrichment found fields=%s for %s",
                    sorted(
                        ai_data.keys()
                    ),
                    getattr(
                        record,
                        "title",
                        "unknown",
                    ),
                )

            except Exception as exc:

                logger.warning(
                    "AI enrichment failed for %s: %s",
                    getattr(
                        record,
                        "title",
                        "unknown",
                    ),
                    exc,
                )

        # --------------------------------------------------------------
        # Convert JobRecord to dict
        # --------------------------------------------------------------

        data = record.model_dump()

        filled: list[str] = []

        # --------------------------------------------------------------
        # Fill fields
        # --------------------------------------------------------------

        for key, value in found.items():

            if key not in data or value is None:
                continue

            current = data.get(
                key
            )

            # Normal ingestion preserves existing collector values.
            # Backfill can explicitly force corrected extraction to replace
            # stale values already stored in the database.
            can_fill = (
                force_replace
                or _is_blank(current)
                or (
                    key == "location"
                    and current == "India"
                )
            )

            if can_fill:

                data[key] = value

                filled.append(
                    key
                )

        # --------------------------------------------------------------
        # Re-validate selection_process regardless of where it came from.
        #
        # The fill loop above only ever touches data["selection_process"]
        # when `found` actually produced a new candidate. If the
        # deterministic extractor and the AI fallback both correctly
        # produced nothing (because no reliable selection section
        # exists), a pre-existing bad value already stored on the record
        # -- e.g. from an earlier, looser version of this extractor --
        # would otherwise survive untouched, including during backfill.
        #
        # So: whatever ended up in data["selection_process"] (freshly
        # filled or carried over from the existing record) is checked
        # against the same validator one more time, and cleared to None
        # if it fails. A non-empty value is never protected just because
        # it is non-empty -- a false positive is strictly worse than
        # None, per policy.
        # --------------------------------------------------------------

        existing_selection = data.get("selection_process")

        if existing_selection and not _valid_selection_process(existing_selection):

            logger.info(
                "Clearing invalid stored selection_process for %s: %r",
                getattr(record, "title", "unknown"),
                existing_selection,
            )

            data["selection_process"] = None

            # Recorded in `filled` (not as a real field name, but as a
            # note) purely so this change (a) triggers the description
            # rebuild/record rebuild below even if nothing else changed,
            # and (b) is visible in the auto-extraction note for anyone
            # auditing why a previously-populated field is now empty.
            filled.append("selection_process removed: failed validation")

        # --------------------------------------------------------------
        # Apply URL
        # --------------------------------------------------------------

        if (
            apply_url
            and _is_blank(
                data.get("apply_url")
            )
        ):

            data["apply_url"] = (
                apply_url
            )

            filled.append(
                "apply_url"
            )

        # --------------------------------------------------------------
        # Notification PDF URL
        # --------------------------------------------------------------

        if (
            pdf_url
            and pdf_url
            != data.get(
                "notification_url"
            )
            and _is_blank(
                data.get(
                    "notification_url"
                )
            )
        ):

            data[
                "notification_url"
            ] = pdf_url

            filled.append(
                "notification_url"
            )

        # --------------------------------------------------------------
        # Description
        # --------------------------------------------------------------

        if filled:

            lines = [
                (
                    f"{data['title']} - "
                    f"{data['organization']}."
                )
            ]

            if (
                data.get(
                    "vacancies"
                )
                is not None
            ):

                lines.append(
                    "Vacancies: "
                    f"{data['vacancies']}."
                )

            if data.get(
                "qualification"
            ):

                lines.append(
                    "Qualification: "
                    f"{data['qualification']}."
                )

            if data.get(
                "age_limit"
            ):

                lines.append(
                    "Age limit: "
                    f"{data['age_limit']}."
                )

            if data.get(
                "age_relaxation"
            ):

                lines.append(
                    "Age relaxation: "
                    f"{data['age_relaxation']}."
                )

            if data.get(
                "application_fee"
            ):

                lines.append(
                    "Application fee: "
                    f"{data['application_fee']}."
                )

            if data.get(
                "salary"
            ):

                lines.append(
                    "Salary: "
                    f"{data['salary']}."
                )

            if data.get(
                "pay_level"
            ):

                lines.append(
                    "Pay level: "
                    f"{data['pay_level']}."
                )

            if data.get(
                "selection_process"
            ):

                lines.append(
                    "Selection process: "
                    f"{data['selection_process']}."
                )

            if data.get(
                "start_date"
            ):

                lines.append(
                    "Application starts: "
                    f"{data['start_date'].strftime('%d %b %Y')}."
                )

            if data.get(
                "deadline"
            ):

                lines.append(
                    "Last date to apply: "
                    f"{data['deadline'].strftime('%d %b %Y')}."
                )

            if data.get(
                "exam_date"
            ):

                lines.append(
                    "Exam date: "
                    f"{data['exam_date'].strftime('%d %b %Y')}."
                )

            source_note = (
                "Auto-extracted from the official "
                "notification ("
                + ", ".join(filled)
                + (
                    "; AI-assisted"
                    if ai_used
                    else ""
                )
                + "). Verify all details against "
                  "the official notice before applying."
            )

            lines.append(
                source_note
            )

            data["description"] = (
                " ".join(lines)
            )

            # ----------------------------------------------------------
            # Build new Pydantic record
            # ----------------------------------------------------------

            return type(record)(
                **data
            )

    except Exception as exc:

        logger.warning(
            "Enrichment failed for %s: %s",
            getattr(
                record,
                "notification_url",
                "?",
            ),
            exc,
        )

    return record


# ==========================================================================
# DATABASE BACKFILL
# ==========================================================================

def enrich_pending_jobs(
    db,
    limit: int = 30,
) -> dict:
    """
    Backfill government jobs that are already in review.

    This is required for existing jobs.
    """

    from sqlalchemy import (
        or_,
        select,
    )

    from app.models.domain import Job

    from app.ingestion.models.job_record import (
        JobRecord,
    )

    # Re-enrich the latest Government jobs so corrected regex/AI
    # extraction can repair stale values already stored in the database.
    rows = db.scalars(
        select(Job)
        .where(
            # Job.status == "review",
            Job.job_type == "Government",
            Job.notification_url.is_not(None),
        )
        .order_by(
            Job.id.desc()
        )
        .limit(limit)
    ).all()

    updated = 0

    for job in rows:

        # --------------------------------------------------------------
        # Convert DB Job -> JobRecord
        # --------------------------------------------------------------

        record = JobRecord(
            source_name=(
                job.source_name
                or "backfill"
            ),

            title=job.title,

            organization=(
                job.organization
                or "Unknown"
            ),

            notification_url=(
                job.notification_url
            ),

            official_url=(
                job.official_url
            ),

            apply_url=(
                job.apply_url
            ),

            qualification=(
                job.qualification
                or "See official notification"
            ),

            description=(
                job.description
                or "See official notification"
            ),

            vacancies=job.vacancies,

            age_limit=(
                job.age_limit
            ),

            age_relaxation=(
                job.age_relaxation
            ),

            application_fee=(
                job.application_fee
            ),

            salary=(
                job.salary
            ),

            pay_level=(
                job.pay_level
            ),

            start_date=(
                job.start_date
            ),

            deadline=(
                job.deadline
            ),

            exam_date=(
                job.exam_date
            ),

            selection_process=(
                job.selection_process
            ),

            ad_number=(
                job.ad_number
            ),

            location=(
                job.location
                or "India"
            ),
        )

        # --------------------------------------------------------------
        # Enrich
        # --------------------------------------------------------------

        enriched = enrich_record(
            record,
            db,
            force_replace=True,
        )

        if enriched is record:
            continue

        # --------------------------------------------------------------
        # Copy fields back to DB
        # --------------------------------------------------------------

        fields = [
            "vacancies",
            "qualification",
            "age_limit",
            "age_relaxation",
            "application_fee",
            "salary",
            "pay_level",
            "start_date",
            "deadline",
            "exam_date",
            "selection_process",
            "ad_number",
            "location",
            "apply_url",
            "notification_url",
            "description",
        ]

        for field in fields:

            setattr(
                job,
                field,
                getattr(
                    enriched,
                    field,
                ),
            )

        updated += 1

    db.commit()

    return {
        "checked": len(rows),
        "updated": updated,
    }