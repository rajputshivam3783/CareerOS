"""Skill assessments: admin-authored questions, candidate attempts,
server-side scoring.

Every question and its correct answer is written by an admin (see
app.api.skill_intelligence admin endpoints) — nothing here generates a
question or infers a "correct" answer. Scoring is deterministic
(exact option match); "weak topics" is a plain aggregation of which
tagged topics the candidate missed, not an AI judgment call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import AssessmentAnswer, AssessmentAttempt, AssessmentQuestion, SkillAssessment


def start_attempt(db: Session, assessment_id: int, user_id: int) -> AssessmentAttempt:
    assessment = db.get(SkillAssessment, assessment_id)
    if not assessment or assessment.status != "published":
        raise HTTPException(404, "Assessment not found")
    questions = list(
        db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.assessment_id == assessment_id))
    )
    if not questions:
        raise HTTPException(400, "This assessment has no questions yet")

    attempt = AssessmentAttempt(
        assessment_id=assessment_id,
        user_id=user_id,
        status="in_progress",
        total_questions=len(questions),
        started_at=datetime.utcnow(),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def _own_in_progress_attempt(db: Session, attempt_id: int, user_id: int) -> AssessmentAttempt:
    attempt = db.get(AssessmentAttempt, attempt_id)
    if not attempt or attempt.user_id != user_id:
        raise HTTPException(404, "Attempt not found")
    if attempt.status != "in_progress":
        raise HTTPException(400, "This attempt has already been submitted")
    return attempt


@dataclass
class AnswerIn:
    question_id: int
    selected_option: int


def submit(db: Session, attempt_id: int, user_id: int, answers: list[AnswerIn]) -> AssessmentAttempt:
    attempt = _own_in_progress_attempt(db, attempt_id, user_id)
    questions = {
        q.id: q
        for q in db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.assessment_id == attempt.assessment_id))
    }

    answered_ids = set()
    correct = 0
    weak_topics: dict[str, int] = {}

    for a in answers:
        q = questions.get(a.question_id)
        if not q or q.id in answered_ids:
            continue
        answered_ids.add(q.id)
        is_correct = a.selected_option == q.correct_option
        if is_correct:
            correct += 1
        else:
            weak_topics[q.topic] = weak_topics.get(q.topic, 0) + 1
        db.add(
            AssessmentAnswer(
                attempt_id=attempt.id, question_id=q.id, selected_option=a.selected_option, is_correct=is_correct
            )
        )

    attempt.correct_count = correct
    attempt.score_percentage = round(100 * correct / attempt.total_questions, 1) if attempt.total_questions else 0.0
    attempt.weak_topics_json = json.dumps(sorted(weak_topics.keys(), key=lambda t: -weak_topics[t]))
    attempt.status = "completed"
    attempt.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(attempt)
    return attempt


def weak_topics_for_user(db: Session, user_id: int, skill_id: int | None = None) -> list[str]:
    """Aggregate weak topics across a candidate's completed attempts —
    used by app.skill_intelligence.practice, not exposed directly as
    an endpoint of its own."""

    stmt = select(AssessmentAttempt).where(AssessmentAttempt.user_id == user_id, AssessmentAttempt.status == "completed")
    if skill_id is not None:
        assessment_ids = [
            a.id for a in db.scalars(select(SkillAssessment).where(SkillAssessment.skill_id == skill_id))
        ]
        stmt = stmt.where(AssessmentAttempt.assessment_id.in_(assessment_ids))

    topics: dict[str, int] = {}
    for attempt in db.scalars(stmt):
        for topic in json.loads(attempt.weak_topics_json or "[]"):
            topics[topic] = topics.get(topic, 0) + 1
    return sorted(topics.keys(), key=lambda t: -topics[t])
