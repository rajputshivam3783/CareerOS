"""V25.4 — Career Agent behavior preferences (spec section 21).

CRUD for CareerAgentPreference — proactive notifications on/off,
frequency, quiet hours, channels. Deliberately separate from
``app.career_copilot.career_preferences`` (career goals/target role),
which is unchanged and untouched by this module.
"""

from __future__ import annotations

from app.models.domain import CareerAgentPreference

FIELDS = ("proactive_enabled", "frequency", "quiet_hours_start", "quiet_hours_end", "channels")
VALID_FREQUENCIES = {"instant", "daily", "weekly"}


class InvalidPreferenceError(ValueError):
    pass


def get(db, user_id: int) -> CareerAgentPreference | None:
    return db.get(CareerAgentPreference, user_id)


def get_or_default(db, user_id: int) -> dict:
    row = get(db, user_id)
    if not row:
        return {
            "proactive_enabled": True, "frequency": "daily", "quiet_hours_start": None,
            "quiet_hours_end": None, "channels": "in_app",
        }
    return {field: getattr(row, field) for field in FIELDS}


def upsert(db, user_id: int, updates: dict) -> CareerAgentPreference:
    if "frequency" in updates and updates["frequency"] is not None and updates["frequency"] not in VALID_FREQUENCIES:
        raise InvalidPreferenceError(f"frequency must be one of {sorted(VALID_FREQUENCIES)}")
    for hour_field in ("quiet_hours_start", "quiet_hours_end"):
        value = updates.get(hour_field)
        if value is not None and not (0 <= int(value) <= 23):
            raise InvalidPreferenceError(f"{hour_field} must be between 0 and 23")

    record = get(db, user_id) or CareerAgentPreference(user_id=user_id)
    for field_name in FIELDS:
        if field_name in updates and updates[field_name] is not None:
            setattr(record, field_name, updates[field_name])
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
