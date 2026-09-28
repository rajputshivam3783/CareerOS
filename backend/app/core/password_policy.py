"""V17.1 Auth Core — password strength scoring and reuse history.

No new dependency is added for this (no zxcvbn): the heuristic below
is intentionally simple and explainable, good enough to back a
strength-meter UI. It never blocks a password on its own — the hard
requirements (min length, confirmation match) are enforced by the
pydantic schemas in app.api.auth; this only produces a 0-4 score plus
human-readable feedback for the frontend to render as a meter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_password
from app.models.domain import PasswordHistory

_COMMON_PASSWORDS = {
    "password", "password123", "12345678", "123456789", "qwerty123",
    "letmein123", "welcome123", "admin1234", "iloveyou1", "changeme123",
}


@dataclass
class PasswordStrength:
    score: int  # 0 (very weak) .. 4 (very strong)
    label: str
    feedback: list[str] = field(default_factory=list)


def score_password(value: str) -> PasswordStrength:
    feedback: list[str] = []
    length = len(value)

    if length < settings.password_min_length:
        feedback.append(f"Use at least {settings.password_min_length} characters")

    variety = sum(
        bool(re.search(pattern, value))
        for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[^a-zA-Z0-9]")
    )
    if variety < 3:
        feedback.append("Mix uppercase, lowercase, numbers, and symbols")

    if value.lower() in _COMMON_PASSWORDS:
        feedback.append("This password is too common")
        variety = 0

    if re.search(r"(.)\1{2,}", value):
        feedback.append("Avoid repeating the same character")

    # Base score off length + character-class variety; a common
    # password is capped low regardless of how long it looks.
    score = 0
    if length >= settings.password_min_length:
        score += 1
    if length >= settings.password_min_length + 4:
        score += 1
    score += max(0, variety - 1)
    score = max(0, min(4, score))
    if value.lower() in _COMMON_PASSWORDS:
        score = min(score, 1)

    labels = {0: "Very weak", 1: "Weak", 2: "Fair", 3: "Strong", 4: "Very strong"}
    if not feedback and score >= 3:
        feedback.append("Good password")
    return PasswordStrength(score=score, label=labels[score], feedback=feedback)


def was_recently_used(db: Session, user_id: int, new_password: str) -> bool:
    """True if ``new_password`` matches any of the user's last
    ``settings.password_history_limit`` passwords (including the
    current one, which callers should check separately if desired)."""
    rows = db.scalars(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user_id)
        .order_by(PasswordHistory.id.desc())
        .limit(settings.password_history_limit)
    ).all()
    return any(verify_password(new_password, row.password_hash) for row in rows)


def record_password_history(db: Session, user_id: int, password_hash: str) -> None:
    """Store the new hash and prune anything beyond the retention limit."""
    db.add(PasswordHistory(user_id=user_id, password_hash=password_hash))
    db.flush()
    rows = db.scalars(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user_id)
        .order_by(PasswordHistory.id.desc())
    ).all()
    for stale in rows[settings.password_history_limit:]:
        db.delete(stale)
