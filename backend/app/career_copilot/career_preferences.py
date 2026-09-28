"""CRUD for the candidate-defined career profile
(``CareerPreference``). All fields are self-reported and optional —
this module never infers or fills a value the candidate didn't
provide; see context_engine.py for how an unset field is surfaced as
"unknown" rather than guessed."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.domain import CareerPreference

FIELDS = (
    "target_role", "preferred_industry", "preferred_location", "preferred_work_mode",
    "experience_level", "target_companies", "salary_expectation", "preferred_skills",
    "learning_goals", "career_goal",
)


def get(db: Session, user_id: int) -> CareerPreference | None:
    return db.get(CareerPreference, user_id)


def upsert(db: Session, user_id: int, updates: dict) -> CareerPreference:
    record = db.get(CareerPreference, user_id) or CareerPreference(user_id=user_id)
    for field_name in FIELDS:
        if field_name in updates and updates[field_name] is not None:
            setattr(record, field_name, updates[field_name])
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
