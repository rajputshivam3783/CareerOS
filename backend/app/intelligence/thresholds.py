"""V25.3 — sample-size thresholds (spec section 21).

Small samples are the main way an analytics layer becomes a liar:
"Rust demand is up 200%" is a true statement about two job postings
and a false statement about anything anyone cares about. Every
aggregate in this package therefore passes through one of the
guards below before it is reported.

The thresholds are **not hardcoded at call sites**. They are V25.2
platform settings, which means they are typed, validated, bounded,
operator-tunable at runtime, audited when changed, and defined in
exactly one place. Adding them cost one entry each in
``SETTING_DEFINITIONS`` and no migration.

Three distinct guards, because "too small to be meaningful" and "too
small to be private" are different questions with different answers:

``MIN_CORPUS``   — below this many jobs in a corpus, no breakdown of
                   that corpus is reported at all.
``MIN_TREND``    — below this many observations in *each* compared
                   period, no trend direction is reported.
``MIN_GROUP``    — below this many distinct entities behind a single
                   reported row, that row is suppressed. This one is a
                   *privacy* guard: "1 candidate in Jaipur knows Rust"
                   is an aggregate in form and an identification in
                   effect.

Every suppression returns a structured reason rather than an empty
list, so the UI can say "insufficient CareerOS data" instead of
rendering a blank chart that looks like zero.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.platform_settings import get_setting_safe

# Fallbacks used only if the settings table cannot be read at all.
# They match the catalog defaults in app.core.platform_settings.
_FALLBACK = {
    "intelligence_min_corpus_jobs": 5,
    "intelligence_min_trend_observations": 10,
    "intelligence_min_group_size": 5,
}

INSUFFICIENT = "insufficient_data"


@dataclass(frozen=True)
class Thresholds:
    min_corpus: int
    min_trend: int
    min_group: int

    def as_dict(self) -> dict:
        return {
            "min_corpus_jobs": self.min_corpus,
            "min_trend_observations": self.min_trend,
            "min_group_size": self.min_group,
        }


def load(db: Session) -> Thresholds:
    return Thresholds(
        min_corpus=int(get_setting_safe(db, "intelligence_min_corpus_jobs", _FALLBACK["intelligence_min_corpus_jobs"])),
        min_trend=int(
            get_setting_safe(db, "intelligence_min_trend_observations", _FALLBACK["intelligence_min_trend_observations"])
        ),
        min_group=int(get_setting_safe(db, "intelligence_min_group_size", _FALLBACK["intelligence_min_group_size"])),
    )


def insufficient(sample_size: int, required: int, *, subject: str = "CareerOS data") -> dict:
    """The one canonical shape for "we will not report this".

    Always carries the actual sample size and the threshold it failed,
    so the answer is auditable rather than a bare refusal — a reader
    can see it was 3 jobs against a threshold of 5, and an operator
    can decide whether the threshold is right.
    """
    return {
        "status": INSUFFICIENT,
        "sample_size": sample_size,
        "required_sample_size": required,
        "message": (
            f"Insufficient {subject} to report this reliably "
            f"({sample_size} observed, {required} required)."
        ),
    }


def suppress_small_groups(rows: list[dict], *, count_key: str, minimum: int) -> tuple[list[dict], int]:
    """Drop rows whose underlying group is smaller than ``minimum``.

    Returns (kept, suppressed_count) so the caller can tell the reader
    that something was withheld. Silently truncating would make a
    partial list look complete, which is its own kind of dishonesty.
    """
    kept = [row for row in rows if int(row.get(count_key, 0)) >= minimum]
    return kept, len(rows) - len(kept)
