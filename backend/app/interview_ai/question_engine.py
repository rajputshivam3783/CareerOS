"""V20.4 — Question engine.

Split deliberately in two, per "keep interview state transitions
deterministic and testable":

  * **Category/difficulty selection is 100% deterministic** — a plain
    rotation over the allowed category pool for the session's
    `interview_type`, and a difficulty ladder driven only by the
    previous evaluation's score (see `next_difficulty`). No AI
    involved, fully unit-testable with no mocking.
  * **Question *phrasing* is the only AI-assisted part** — the model is
    asked to phrase ONE plain-text question (not JSON, nothing else to
    parse) grounded in the facts block and a real seed question from
    `question_bank.py`, for the category/difficulty Python already
    picked. If every provider fails, the seed question itself is used
    verbatim — never a broken or empty question reaches the candidate.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai import completion_service
from app.career_copilot.system_prompt import wrap_untrusted
from app.interview_ai import question_bank
from app.interview_ai.context_builder import InterviewContext, facts_block
from app.models.domain import MockInterviewSession

DIFFICULTY_LADDER = ["easy", "medium", "hard"]

_TECHNICAL_ROTATION = ["programming", "dsa", "oop", "dbms", "os", "computer_networks", "system_design", "cloud", "sql"]
_DATA_SCIENCE_ROTATION = ["data_science", "machine_learning", "sql"]
_BEHAVIORAL_ROTATION = list(question_bank.ALL_BEHAVIORAL_AREA_KEYS)

_SYSTEM_PROMPT = """You are an experienced technical/behavioral interviewer conducting a mock interview. \
You will be given: the interview category and difficulty already decided (do not change them), factual context \
about the candidate/job, and one example question in that category as a style reference.

Your only job: phrase ONE clear, natural interview question in that exact category and difficulty, grounded in \
the given facts. Do not invent facts about the candidate, the job, or their resume that weren't given to you. \
If asking about a specific resume project, refer to it by the name given, verbatim — never invent a project name.

Respond with ONLY the question text. No preamble, no numbering, no quotation marks, no explanation."""


def next_difficulty(current_difficulty: str, last_overall_score: int | None) -> str:
    """Deterministic difficulty ladder. `last_overall_score` is None
    for the very first question (no prior evaluation) -> stays put."""
    if last_overall_score is None:
        return current_difficulty
    idx = DIFFICULTY_LADDER.index(current_difficulty) if current_difficulty in DIFFICULTY_LADDER else 1
    if last_overall_score >= 80:
        return DIFFICULTY_LADDER[min(idx + 1, len(DIFFICULTY_LADDER) - 1)]
    if last_overall_score < 40:
        return DIFFICULTY_LADDER[max(idx - 1, 0)]
    return current_difficulty


def _category_for_sequence(interview_type: str, sequence: int, focus_skills: list[str]) -> str:
    if interview_type == "hr":
        return "hr"
    if interview_type == "behavioral":
        return _BEHAVIORAL_ROTATION[sequence % len(_BEHAVIORAL_ROTATION)]
    if interview_type == "coding":
        return "coding"
    if interview_type == "system_design":
        return "system_design"
    if interview_type == "data_science":
        return _DATA_SCIENCE_ROTATION[sequence % len(_DATA_SCIENCE_ROTATION)]
    if interview_type == "custom" and focus_skills:
        pool = [s.lower().replace(" ", "_") for s in focus_skills if s.lower().replace(" ", "_") in _TECHNICAL_ROTATION]
        if pool:
            return pool[sequence % len(pool)]
    if interview_type == "mixed":
        cycle = sequence % 3
        if cycle == 0:
            return _TECHNICAL_ROTATION[sequence % len(_TECHNICAL_ROTATION)]
        if cycle == 1:
            return _BEHAVIORAL_ROTATION[sequence % len(_BEHAVIORAL_ROTATION)]
        return "hr"
    if interview_type in ("resume_based", "job_specific"):
        return "resume_project" if interview_type == "resume_based" else "job_requirement"
    # technical (default/fallback)
    return _TECHNICAL_ROTATION[sequence % len(_TECHNICAL_ROTATION)]


def _seed_question(category: str, difficulty: str, ctx: InterviewContext, already_asked: set[str], sequence: int) -> tuple[str, str, str | None]:
    """Returns (question_text, source, source_detail) from
    deterministic, non-AI material — used as both the AI's style seed
    and the no-AI fallback."""
    if category == "hr":
        q = question_bank.sample_hr(already_asked) or "Tell me a bit about yourself."
        return q, "question_bank", None
    if category in question_bank.ALL_BEHAVIORAL_AREA_KEYS:
        q = question_bank.sample_behavioral(category, already_asked) or "Tell me about a challenging situation at work and how you handled it."
        return q, "question_bank", None
    if category == "resume_project":
        if ctx.known_project_names:
            project = ctx.known_project_names[sequence % len(ctx.known_project_names)]
            return f"Tell me about your project '{project}' — the architecture, your specific contribution, and a challenge you faced.", "resume_project", project
        return "Tell me about a project from your resume that you're most proud of.", "question_bank", None
    if category == "job_requirement":
        if ctx.job and ctx.job.skills:
            skills = [s.strip() for s in ctx.job.skills.split(",") if s.strip()]
            if skills:
                skill = skills[sequence % len(skills)]
                return f"This role requires {skill}. Tell me about your experience with it.", "job_skill", skill
        return "What makes you a strong fit for this role based on your background?", "question_bank", None
    if category == "coding":
        problem = question_bank.sample_coding_problem(difficulty, already_asked)
        if problem:
            text = f"{problem['title']}: {problem['statement']} Constraints: {problem['constraints']}. Example: {problem['examples']}"
            return text, "question_bank", problem["title"]
        return "Describe an algorithm to reverse a linked list in place.", "question_bank", None
    q = question_bank.sample_technical(category, difficulty, already_asked)
    if q:
        return q, "question_bank", None
    return f"Tell me about your experience with {category.replace('_', ' ')}.", "question_bank", None


def generate_next_question(
    db: Session,
    session: MockInterviewSession,
    ctx: InterviewContext,
    *,
    already_asked_text: set[str],
    user_id: int,
) -> dict:
    """Returns a dict of the fields needed to create a
    MockInterviewQuestion — does not persist it (the API layer owns
    the transaction, same convention as every other write path)."""
    category = _category_for_sequence(session.interview_type, session.current_question_index, ctx.focus_skills)
    difficulty = session.current_difficulty
    seed_text, source, source_detail = _seed_question(category, difficulty, ctx, already_asked_text, session.current_question_index)

    final_text = seed_text
    try:
        result = completion_service.generate(
            db,
            operation="interview_ai.question",
            system_prompt=_SYSTEM_PROMPT,
            user_message=(
                f"Category: {category}\nDifficulty: {difficulty}\n"
                f"Example question in this category (style reference only, do not repeat verbatim): {seed_text}\n\n"
                + wrap_untrusted("interview context (job/resume facts)", facts_block(ctx))
            ),
            user_id=user_id,
            max_tokens=200,
        )
        candidate_text = result.text.strip().strip('"')
        if candidate_text and candidate_text not in already_asked_text:
            final_text = candidate_text
            source = source if source != "question_bank" else "ai_generated"
    except completion_service.CompletionError:
        pass  # graceful degradation — the seed question from question_bank.py is already a complete, valid question

    return {
        "category": category,
        "difficulty": difficulty,
        "question_text": final_text,
        "source": source,
        "source_detail": source_detail,
    }
