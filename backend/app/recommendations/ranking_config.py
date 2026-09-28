"""RANKING CONFIGURATION — V21.4.

Every tunable number the personalization/ranking pipeline uses lives
here, with a documented default (see RANKING_ENGINE_V21_4.md for the
full table and rationale for each value) and an optional admin
override stored in ``RankingConfiguration`` (one row per key,
``value_json``). A missing row means "use the default below" — this
module is fully functional against an empty table, which is the
out-of-the-box state.

Nothing here is exposed to normal candidates — only
``GET/PUT /job-recommendations/admin/ranking-config``
(admin_guard-gated, app/api/recommendations.py) can read or change it,
per "Do NOT expose dangerous internal configuration directly to normal
users."

SIGNAL QUALITY — event weights (Apply > Save > Open > Impression, per
spec's own example), documented and configurable rather than
scattered magic numbers:

    apply            : +1.00   (strongest positive signal)
    save             : +0.60
    interested       : +0.50
    share            : +0.40
    open             : +0.30
    filter_usage     : +0.10
    impression       : +0.05   (weakest positive signal — just "shown")
    not_interested   : -0.40
    dismiss          : -0.60
    not_relevant     : -0.80   (strongest negative signal)

These are deliberately NOT derived from any learned model — they are
documented business assumptions an admin can retune, exactly as the
spec requires ("Do NOT hard-code arbitrary business assumptions
without documenting them").
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.domain import RankingConfiguration

# --- Component weights (base match score) ---
# Extends V21.3's app.recommendations.scoring._BASE_WEIGHTS with two
# new components: "behavior" (learned from BehaviorSignalAggregate)
# and "deadline_urgency" (freshness/deadline stage in the spec's
# pipeline diagram). Existing components' weights are reduced
# proportionally so the full set still sums to 100 at baseline; see
# RANKING_ENGINE_V21_4.md for the before/after table.
DEFAULT_COMPONENT_WEIGHTS: dict[str, float] = {
    "skill": 26,
    "resume": 13,
    "experience": 13,
    "education": 9,
    "location": 9,
    "career_goal": 9,
    "work_mode": 4,
    "recency": 4,
    "behavior": 9,
    "deadline_urgency": 4,
}

DEFAULT_EVENT_WEIGHTS: dict[str, float] = {
    "apply": 1.00,
    "save": 0.60,
    "interested": 0.50,
    "share": 0.40,
    "open": 0.30,
    "filter_usage": 0.10,
    "impression": 0.05,
    "not_interested": -0.40,
    "dismiss": -0.60,
    "not_relevant": -0.80,
}

# TIME DECAY: half-life in days for a behavior signal's contribution.
# score_after(t days) = score_before * 0.5 ** (t / half_life). A fresh
# "apply" (+1.00) has decayed to ~0.5 after one half-life, ~0.25 after
# two, etc. — recent behavior dominates, old behavior fades but is
# never abruptly deleted.
DEFAULT_TIME_DECAY_HALF_LIFE_DAYS: float = 21.0

# NEGATIVE SIGNALS: a per-signal-key score is clamped to this range so
# a single strong negative interaction (or a short burst of them)
# cannot zero out — let alone permanently exclude — an entire
# category; it only ever dampens that category's boost, and continues
# decaying toward zero afterward like any other signal.
SCORE_CLAMP = (-5.0, 10.0)

# DEDUPLICATION windows (EVENT PROCESSING: "Avoid duplicate events").
IMPRESSION_DEDUPE_HOURS = 24
GENERIC_EVENT_DEDUPE_SECONDS = 30

# DATA RETENTION: raw RecommendationEvent rows older than this are
# eligible for aggregation/purge (see app.recommendations.retention).
# Aggregated signals (BehaviorSignalAggregate) are never subject to
# this — they're already a bounded, permanently-relevant summary.
RAW_EVENT_RETENTION_DAYS = 180

_DEFAULTS: dict[str, object] = {
    "component_weights": DEFAULT_COMPONENT_WEIGHTS,
    "event_weights": DEFAULT_EVENT_WEIGHTS,
    "time_decay_half_life_days": DEFAULT_TIME_DECAY_HALF_LIFE_DAYS,
    "score_clamp": list(SCORE_CLAMP),
    "impression_dedupe_hours": IMPRESSION_DEDUPE_HOURS,
    "generic_event_dedupe_seconds": GENERIC_EVENT_DEDUPE_SECONDS,
    "raw_event_retention_days": RAW_EVENT_RETENTION_DAYS,
}

VALID_CONFIG_KEYS = set(_DEFAULTS)


def get(db: Session, key: str):
    """Returns the effective value for ``key`` — the admin override if
    one is stored, otherwise the documented default. Raises
    ``KeyError`` for an unknown key (never silently returns None for a
    typo'd config key)."""
    if key not in _DEFAULTS:
        raise KeyError(f"Unknown ranking configuration key '{key}'. Expected one of {sorted(_DEFAULTS)}")
    row = db.get(RankingConfiguration, key)
    if row is None:
        return _DEFAULTS[key]
    try:
        return json.loads(row.value_json)
    except (ValueError, TypeError):
        # A corrupted override should never break ranking — fall back
        # to the documented default and let an admin notice/fix it via
        # GET, rather than raising into the ranking hot path.
        return _DEFAULTS[key]


def get_all_effective(db: Session) -> dict[str, object]:
    return {key: get(db, key) for key in _DEFAULTS}


def set_value(db: Session, key: str, value, *, updated_by: int | None = None) -> RankingConfiguration:
    if key not in _DEFAULTS:
        raise KeyError(f"Unknown ranking configuration key '{key}'. Expected one of {sorted(_DEFAULTS)}")
    row = db.get(RankingConfiguration, key)
    encoded = json.dumps(value)
    if row is None:
        row = RankingConfiguration(config_key=key, value_json=encoded, updated_by=updated_by)
        db.add(row)
    else:
        row.value_json = encoded
        row.updated_by = updated_by
    db.commit()
    db.refresh(row)
    return row


def reset_to_defaults(db: Session) -> None:
    """Deletes every stored override, reverting all config keys to
    their documented defaults in one call — used by tests and
    available to an admin who wants a clean slate."""
    db.query(RankingConfiguration).delete()
    db.commit()
