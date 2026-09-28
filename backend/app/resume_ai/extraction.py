"""Deterministic structured-field extraction from raw resume text.

Deliberately **not** an LLM call. Structured facts (name, email, phone,
links, which section contains what) are extracted with regex and
section-header matching, the same "best-effort, honest about what it
didn't find" posture as ``app.services.resume_parser`` and the V5 PDF
notification parser: a field that can't be confidently found is
reported as not found, never guessed. This is what makes the
hallucination-prevention requirement structurally true rather than
merely requested — the fields most valuable to fabricate believably
(employers, dates, degrees) never touch a model at all in this step;
see AI_RESUME_PRIVACY.md.

The only place a model is *ever* involved is later, in the wording-only
generative modules (bullet_improver, summary_generator,
project_improver, job_advice), and even those are instructed to work
only from what this module already extracted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NOT_FOUND = "Not found in resume"

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(\+?\d{1,3}[\s-]?)?(\d{10}|\d{3}[\s-]\d{3}[\s-]\d{4})(?!\d)")
_GITHUB_RE = re.compile(r"(https?://)?(www\.)?github\.com/[A-Za-z0-9_-]+/?", re.I)
_LINKEDIN_RE = re.compile(r"(https?://)?(www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?", re.I)
_URL_RE = re.compile(r"https?://[^\s)>\]]+", re.I)

# Section header aliases -> canonical section name. Matched against a
# trimmed, lowercased line that is short (a heading, not a sentence)
# and either ALL CAPS, Title Case, or ends without terminal punctuation
# — the same heuristics resumes overwhelmingly follow.
_SECTION_ALIASES: dict[str, str] = {
    "summary": "summary", "professional summary": "summary", "objective": "summary",
    "profile": "summary", "career objective": "summary", "about me": "summary", "about": "summary",
    "skills": "skills", "technical skills": "skills", "core skills": "skills",
    "skills & tools": "skills", "key skills": "skills", "areas of expertise": "skills",
    "soft skills": "soft_skills", "interpersonal skills": "soft_skills",
    "experience": "experience", "work experience": "experience", "professional experience": "experience",
    "employment history": "experience", "work history": "experience",
    "education": "education", "academic background": "education", "academic qualifications": "education",
    "projects": "projects", "personal projects": "projects", "academic projects": "projects",
    "certifications": "certifications", "certificates": "certifications", "licenses & certifications": "certifications",
    "achievements": "achievements", "accomplishments": "achievements", "awards": "achievements",
    "awards & honors": "achievements", "honors": "achievements",
    "languages": "languages", "language proficiency": "languages",
}
_SECTION_KEYS = ["summary", "skills", "soft_skills", "experience", "education", "projects", "certifications", "achievements", "languages"]


@dataclass
class ExtractedResume:
    """Everything pulled from raw resume text before normalization.
    Every field is either a real value found in the text or the
    literal ``NOT_FOUND`` sentinel — never a guess."""

    name: str = NOT_FOUND
    email: str = NOT_FOUND
    phone: str = NOT_FOUND
    location: str = NOT_FOUND
    github: str = NOT_FOUND
    linkedin: str = NOT_FOUND
    portfolio: str = NOT_FOUND
    sections: dict[str, str] = field(default_factory=dict)  # canonical section name -> raw text
    unclassified_text: str = ""  # anything not captured under a recognized section header


def _is_heading_line(line: str) -> tuple[str, str] | None:
    """Returns (canonical_section_name, inline_content) when this line
    is a section heading. inline_content is "" for a plain heading
    line ("SKILLS" or "Skills:" on its own line, content follows on
    later lines) and non-empty for an inline single-line section
    ("Skills: Python, SQL, AWS") — a common compact resume format
    that must not be silently dropped as unclassified preamble."""
    stripped = line.strip()
    if ":" in stripped:
        head, _, rest = stripped.partition(":")
        head, rest = head.strip(), rest.strip()
        if head and len(head) <= 40:
            canonical = _SECTION_ALIASES.get(head.lower())
            if canonical:
                return canonical, rest
    plain = stripped.strip(":").strip()
    if not plain or len(plain) > 40:
        return None
    canonical = _SECTION_ALIASES.get(plain.lower())
    return (canonical, "") if canonical else None


def _split_sections(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    sections: dict[str, list[str]] = {}
    preamble: list[str] = []
    current: str | None = None

    for line in lines:
        heading = _is_heading_line(line)
        if heading:
            current, inline_content = heading
            sections.setdefault(current, [])
            if inline_content:
                sections[current].append(inline_content)
            continue
        if current:
            sections[current].append(line)
        else:
            preamble.append(line)

    return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}, "\n".join(preamble).strip()


def _extract_name(preamble: str, full_text: str) -> str:
    # Heuristic: the first non-empty line of the document that isn't an
    # email/phone/URL and looks like a short "First Last"-shaped line
    # (2-4 words, no digits) is almost always the candidate's name on a
    # resume — this is how virtually every resume template places it.
    # If nothing matches that shape, we say so rather than guessing.
    candidates = (preamble or full_text).splitlines()
    for line in candidates[:6]:
        stripped = line.strip()
        if not stripped or len(stripped) > 60:
            continue
        if _EMAIL_RE.search(stripped) or _URL_RE.search(stripped) or _PHONE_RE.search(stripped):
            continue
        words = stripped.split()
        if 1 < len(words) <= 5 and not any(ch.isdigit() for ch in stripped):
            return stripped
    return NOT_FOUND


def _extract_location(preamble: str, full_text: str) -> str:
    # Deliberately conservative: only a line that looks like
    # "City, State"/"City, Country" near the top is trusted. A wrong
    # guess here (e.g. picking up a company's HQ city from the
    # experience section) is worse than reporting "not found".
    top = (preamble or full_text).splitlines()[:8]
    location_re = re.compile(r"^[A-Za-z .]{2,30},\s?[A-Za-z .]{2,30}$")
    for line in top:
        stripped = line.strip()
        if location_re.match(stripped) and not _EMAIL_RE.search(stripped):
            return stripped
    return NOT_FOUND


def extract(resume_text: str) -> ExtractedResume:
    text = resume_text or ""
    sections, preamble = _split_sections(text)

    email_match = _EMAIL_RE.search(text)
    phone_match = _PHONE_RE.search(text)
    github_match = _GITHUB_RE.search(text)
    linkedin_match = _LINKEDIN_RE.search(text)

    portfolio = NOT_FOUND
    for url in _URL_RE.findall(text):
        if "github.com" in url.lower() or "linkedin.com" in url.lower():
            continue
        portfolio = url
        break

    return ExtractedResume(
        name=_extract_name(preamble, text),
        email=email_match.group(0) if email_match else NOT_FOUND,
        phone=phone_match.group(0).strip() if phone_match else NOT_FOUND,
        location=_extract_location(preamble, text),
        github=github_match.group(0) if github_match else NOT_FOUND,
        linkedin=linkedin_match.group(0) if linkedin_match else NOT_FOUND,
        portfolio=portfolio,
        sections=sections,
        unclassified_text=preamble,
    )


def detect_tables_or_columns(filename: str, file_bytes: bytes) -> bool | None:
    """Best-effort, format-limited layout risk signal for
    ats_analysis.py. Only DOCX can be checked reliably with the
    libraries already used elsewhere in this codebase
    (``python-docx``, same as ``app.services.resume_parser``) — a
    document with one or more tables is flagged, since ATS parsers are
    well documented to sometimes read table cells out of visual order.
    PDF column detection would require real layout/geometry analysis
    this project doesn't do (pypdf, used elsewhere here, only exposes
    linear text) — returns None (unknown) rather than guessing.
    Must be called with the file's bytes still in memory (at upload
    time); nothing about a resume's original file is persisted, so
    this can't be computed later. See Resume.has_tables_or_columns.
    """
    name = (filename or "").lower()
    if not name.endswith(".docx"):
        return None
    try:
        from io import BytesIO

        from docx import Document

        document = Document(BytesIO(file_bytes))
        return len(document.tables) > 0
    except Exception:
        return None
