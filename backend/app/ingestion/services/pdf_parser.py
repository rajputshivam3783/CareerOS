"""V5 — best-effort extraction of structured fields from a recruitment
notification PDF.

This is deliberately heuristic (regex over extracted text), not a
guaranteed-correct parser: official notifications vary hugely in
layout, wording, and formatting. Every extracted field is reported
alongside whether it was actually found, so a human reviewer can see
at a glance what to double-check — and the calling code always routes
the result through the normal review queue rather than publishing
directly, exactly like every other ingestion path in this project.
"""

import re
from datetime import date, datetime
from io import BytesIO

from pypdf import PdfReader

# Recognized date formats in Indian government notifications, roughly
# most-specific first.
_DATE_FORMATS = ["%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y"]

_FIELD_PATTERNS: dict[str, list[str]] = {
    "qualification": [
        r"educational qualification[s]?\s*[:\-]?\s*(.+)",
        r"eligibility\s*[:\-]?\s*(.+)",
        r"qualification[s]?\s*[:\-]?\s*(.+)",
    ],
    "age_limit": [
        r"age limit\s*[:\-]?\s*(.+)",
        r"upper age limit\s*[:\-]?\s*(.+)",
    ],
    "vacancies_text": [
        r"(?:no\.?\s*of\s*)?(?:total\s*)?vacanc(?:y|ies)\s*[:\-]?\s*(.+)",
        r"total (?:no\.?\s*of\s*)?posts?\s*[:\-]?\s*(.+)",
    ],
    "application_fee": [
        r"application fee\s*[:\-]?\s*(.+)",
        r"examination fee\s*[:\-]?\s*(.+)",
    ],
    "deadline_text": [
        r"last date (?:for|of)? ?(?:submission|receipt|apply)?(?:\s*of\s*application)?\s*[:\-]?\s*(.+)",
        r"closing date\s*[:\-]?\s*(.+)",
    ],
    "exam_date_text": [
        r"(?:date of )?examination\s*[:\-]?\s*(.+)",
        r"exam date\s*[:\-]?\s*(.+)",
    ],
}


def extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF. Returns an empty string (rather
    than raising) for an unreadable/corrupt/scanned-image PDF — the
    caller treats that as "nothing extracted", not a hard failure."""
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            # Cut at the next likely field label or line break so we
            # don't swallow the rest of the page into one field.
            value = re.split(r"\n{2,}|\.\s{2,}", value)[0].strip()
            if value:
                return value[:600]
    return None


def _try_parse_date(text_fragment: str) -> date | None:
    candidate = re.search(r"\d{1,2}[-/. ]\w+[-/. ]\d{2,4}", text_fragment)
    raw = candidate.group(0) if candidate else text_fragment[:40]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_notification_fields(pdf_bytes: bytes) -> dict:
    """Best-effort structured extraction from a notification PDF.

    Returns a dict with the extracted fields (None where nothing
    matched) plus a ``fields_found`` list naming what was actually
    extracted, so downstream review can see extraction confidence at
    a glance instead of trusting a fully-populated-looking record.
    """
    text = extract_text(pdf_bytes)
    if not text.strip():
        return {
            "qualification": None,
            "age_limit": None,
            "vacancies": None,
            "application_fee": None,
            "deadline": None,
            "exam_date": None,
            "fields_found": [],
            "extraction_note": "Could not extract text — the PDF may be a scanned image without OCR text.",
        }

    qualification = _first_match(text, _FIELD_PATTERNS["qualification"])
    age_limit = _first_match(text, _FIELD_PATTERNS["age_limit"])
    vacancies_text = _first_match(text, _FIELD_PATTERNS["vacancies_text"])
    application_fee = _first_match(text, _FIELD_PATTERNS["application_fee"])
    deadline_text = _first_match(text, _FIELD_PATTERNS["deadline_text"])
    exam_date_text = _first_match(text, _FIELD_PATTERNS["exam_date_text"])

    vacancies = None
    if vacancies_text:
        digits = re.search(r"\d[\d,]*", vacancies_text)
        if digits:
            try:
                vacancies = int(digits.group(0).replace(",", ""))
            except ValueError:
                vacancies = None

    deadline = _try_parse_date(deadline_text) if deadline_text else None
    exam_date = _try_parse_date(exam_date_text) if exam_date_text else None

    fields_found = [
        name
        for name, value in [
            ("qualification", qualification),
            ("age_limit", age_limit),
            ("vacancies", vacancies),
            ("application_fee", application_fee),
            ("deadline", deadline),
            ("exam_date", exam_date),
        ]
        if value is not None
    ]

    return {
        "qualification": qualification,
        "age_limit": age_limit,
        "vacancies": vacancies,
        "application_fee": application_fee,
        "deadline": deadline,
        "exam_date": exam_date,
        "fields_found": fields_found,
        "extraction_note": (
            "Heuristic extraction — always verify every field against the source PDF before publishing."
        ),
    }
