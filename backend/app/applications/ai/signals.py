"""V22.4 — Deterministic Application Health Engine.

NO LLM CALL ANYWHERE IN THIS FILE. Per the spec: "Do not let an LLM
arbitrarily generate the numeric score. The backend should calculate
deterministic signals." Every number and label here is a plain
function of data already in the database, always available even when
every AI provider is down, and always reproducible — the same
application state always yields the same health score, priority,
next-best-action, follow-up timing, risk list, and action plan. AI
(narrative.py) only ever explains these signals in prose; it never
recomputes or overrides them.

Thresholds are named constants rather than magic numbers so the
"explainable" requirement holds — every `+`/`-` reason in
``HealthResult.reasons`` traces back to one of these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications.status import TERMINAL_STATUSES
from app.models.domain import Application, ApplicationEvent, ApplicationInterview, ApplicationStatusHistory, ApplicationTask

# --- thresholds (days) ---------------------------------------------------
RECENT_ACTIVITY_DAYS = 3
STALE_DAYS = 21
VERY_STALE_DAYS = 45
DEADLINE_SOON_DAYS = 3
DEADLINE_IMMINENT_DAYS = 1
INTERVIEW_SOON_DAYS = 3

# status -> (consider_soon_days, follow_up_today_days, urgent_days), i.e.
# days since last activity before each follow-up recommendation kicks in.
# Statuses not listed never recommend a follow-up (SAVED/PLANNING_TO_APPLY
# haven't been submitted anywhere yet; terminal statuses are closed).
FOLLOW_UP_THRESHOLDS: dict[str, tuple[int, int, int]] = {
    "APPLIED": (7, 10, 21),
    "ASSESSMENT": (3, 5, 10),
    "INTERVIEW": (3, 5, 10),
    "OFFER": (1, 2, 5),
}

_FOLLOW_UP_KEYWORDS = ("follow up", "follow-up", "followup")

HEALTH_LABELS = ("Healthy", "Needs Attention", "At Risk", "Stale")
PRIORITY_LEVELS = ("Low", "Medium", "High", "Critical")


@dataclass
class HealthResult:
    score: int
    label: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class NextAction:
    action: str
    reason: str
    timing: str


@dataclass
class Risk:
    risk: str
    severity: str  # low / medium / high
    reason: str
    recommended_action: str


@dataclass
class ActionPlanItem:
    bucket: str  # TODAY / NEXT_2_DAYS / BEFORE_INTERVIEW / AFTER_INTERVIEW
    title: str
    priority: str
    reason: str
    due_date: str | None = None


@dataclass
class ApplicationSignals:
    application_id: int
    status: str
    days_since_last_activity: int | None
    last_activity_at: datetime | None
    deadline_days_left: int | None
    upcoming_interview: ApplicationInterview | None
    overdue_task_count: int
    has_pending_follow_up_task: bool
    missing_recruiter_contact: bool
    health: HealthResult
    priority: str
    next_action: NextAction
    follow_up_timing: str
    follow_up_reason: str
    risks: list[Risk]
    action_plan: list[ActionPlanItem]

    def fingerprint(self) -> dict:
        """The subset of this that would change AI output — used to
        build a cache context_key (see app.applications.ai.cache).
        Deliberately excludes wording/reason text (which can be
        re-derived) and keeps only the facts that determine it."""
        return {
            "status": self.status,
            "days_since_last_activity": self.days_since_last_activity,
            "deadline_days_left": self.deadline_days_left,
            "upcoming_interview_id": self.upcoming_interview.id if self.upcoming_interview else None,
            "upcoming_interview_result": self.upcoming_interview.result if self.upcoming_interview else None,
            "overdue_task_count": self.overdue_task_count,
            "health_score": self.health.score,
            "priority": self.priority,
            "next_action": self.next_action.action,
            "follow_up_timing": self.follow_up_timing,
        }


def _last_activity_at(db: Session, application: Application) -> datetime | None:
    candidates = [application.status_updated_at, application.created_at]
    latest_history = db.scalar(
        select(ApplicationStatusHistory.changed_at)
        .where(ApplicationStatusHistory.application_id == application.id)
        .order_by(ApplicationStatusHistory.changed_at.desc())
        .limit(1)
    )
    latest_event = db.scalar(
        select(ApplicationEvent.occurred_at)
        .where(ApplicationEvent.application_id == application.id)
        .order_by(ApplicationEvent.occurred_at.desc())
        .limit(1)
    )
    for candidate in (latest_history, latest_event):
        if candidate:
            candidates.append(candidate)
    return max((c for c in candidates if c), default=None)


def _upcoming_interview(db: Session, application_id: int) -> ApplicationInterview | None:
    return db.scalar(
        select(ApplicationInterview)
        .where(
            ApplicationInterview.application_id == application_id,
            ApplicationInterview.scheduled_at.is_not(None),
            ApplicationInterview.scheduled_at >= datetime.utcnow(),
            ApplicationInterview.result.in_(("SCHEDULED", "RESCHEDULED")),
        )
        .order_by(ApplicationInterview.scheduled_at.asc())
        .limit(1)
    )


def _recently_concluded_interview(db: Session, application_id: int) -> ApplicationInterview | None:
    """An interview whose scheduled time has passed but whose result
    hasn't been updated yet — used to prompt a post-interview
    follow-up in the action plan."""
    return db.scalar(
        select(ApplicationInterview)
        .where(
            ApplicationInterview.application_id == application_id,
            ApplicationInterview.scheduled_at.is_not(None),
            ApplicationInterview.scheduled_at < datetime.utcnow(),
            ApplicationInterview.result == "SCHEDULED",
        )
        .order_by(ApplicationInterview.scheduled_at.desc())
        .limit(1)
    )


def _has_pending_follow_up_task(db: Session, application_id: int) -> bool:
    titles = db.scalars(
        select(ApplicationTask.title).where(ApplicationTask.application_id == application_id, ApplicationTask.completed.is_(False))
    ).all()
    return any(any(kw in (t or "").lower() for kw in _FOLLOW_UP_KEYWORDS) for t in titles)


def _compute_health(
    *, status: str, days_since_last_activity: int | None, deadline_days_left: int | None,
    upcoming_interview: ApplicationInterview | None, overdue_task_count: int, missing_recruiter_contact: bool,
) -> HealthResult:
    if status == "ACCEPTED":
        return HealthResult(100, "Healthy", ["+ Offer accepted"])
    if status in ("REJECTED", "WITHDRAWN", "GHOSTED"):
        return HealthResult(50, "Stale", ["This application is closed — health scoring no longer applies"])

    score = 60
    reasons: list[str] = []

    if days_since_last_activity is not None:
        if days_since_last_activity <= RECENT_ACTIVITY_DAYS:
            score += 15
            reasons.append("+ Recent activity")
        elif days_since_last_activity >= VERY_STALE_DAYS:
            score -= 30
            reasons.append(f"- No activity in {days_since_last_activity} days")
        elif days_since_last_activity >= STALE_DAYS:
            score -= 20
            reasons.append(f"- No activity in {days_since_last_activity} days")

    if upcoming_interview is not None:
        score += 15
        reasons.append("+ Interview scheduled")

    if overdue_task_count > 0:
        score -= min(20, 10 * overdue_task_count)
        reasons.append(f"- {overdue_task_count} overdue task(s)")
    else:
        score += 5
        reasons.append("+ No overdue tasks")

    if deadline_days_left is not None:
        if deadline_days_left <= DEADLINE_IMMINENT_DAYS:
            score -= 15
            reasons.append("- Deadline imminent")
        elif deadline_days_left <= DEADLINE_SOON_DAYS:
            score -= 10
            reasons.append("- Deadline approaching")

    if missing_recruiter_contact and status in ("INTERVIEW", "OFFER"):
        score -= 5
        reasons.append("- No recruiter contact on file")

    score = max(0, min(100, score))
    if score >= 75:
        label = "Healthy"
    elif score >= 55:
        label = "Needs Attention"
    elif score >= 35:
        label = "At Risk"
    else:
        label = "Stale"
    return HealthResult(score, label, reasons)


def _compute_priority(
    *, status: str, health: HealthResult, deadline_days_left: int | None,
    upcoming_interview: ApplicationInterview | None, overdue_task_count: int,
) -> str:
    if status in TERMINAL_STATUSES or status in ("SAVED", "PLANNING_TO_APPLY"):
        return "Low"
    if deadline_days_left is not None and deadline_days_left <= DEADLINE_IMMINENT_DAYS:
        return "Critical"
    if upcoming_interview is not None:
        days_to_interview = (upcoming_interview.scheduled_at.date() - date.today()).days
        if days_to_interview <= 1:
            return "Critical"
        if days_to_interview <= INTERVIEW_SOON_DAYS:
            return "High"
    if overdue_task_count >= 2 or health.label == "At Risk":
        return "High"
    if health.label == "Stale" or overdue_task_count == 1:
        return "Medium"
    return "Medium" if health.label == "Needs Attention" else "Low"


def _compute_next_action(
    *, status: str, days_since_last_activity: int | None, deadline_days_left: int | None,
    upcoming_interview: ApplicationInterview | None, overdue_task_count: int, follow_up_timing: str,
) -> NextAction:
    if status == "ACCEPTED":
        return NextAction("No action required", "Offer accepted — congratulations! Nothing further to track here.", "\u2014")
    if status in ("REJECTED", "WITHDRAWN", "GHOSTED"):
        return NextAction("No action required", "This application is closed.", "\u2014")
    if status == "SAVED":
        return NextAction("Apply now", "This job is saved but you haven't applied yet.", "This week")
    if status == "PLANNING_TO_APPLY":
        return NextAction("Review job requirements", "Marked as planning to apply — review the requirements before submitting.", "Soon")
    if deadline_days_left is not None and 0 <= deadline_days_left <= DEADLINE_SOON_DAYS and status not in TERMINAL_STATUSES:
        return NextAction(
            "Update application",
            f"The application deadline is in {max(deadline_days_left, 0)} day(s).",
            "Today" if deadline_days_left <= DEADLINE_IMMINENT_DAYS else "This week",
        )
    if upcoming_interview is not None:
        days_to_interview = (upcoming_interview.scheduled_at.date() - date.today()).days
        if days_to_interview <= INTERVIEW_SOON_DAYS:
            return NextAction(
                "Prepare for interview",
                f"{'Interview' if not upcoming_interview.round_name else upcoming_interview.round_name} is scheduled for {upcoming_interview.scheduled_at.strftime('%b %d')}.",
                "Today" if days_to_interview <= 1 else "This week",
            )
    if status == "ASSESSMENT":
        return NextAction("Complete assessment", "This application is waiting on an assessment.", "As soon as possible")
    if overdue_task_count > 0:
        return NextAction(
            "Update application",
            f"{overdue_task_count} task(s) are overdue on this application.",
            "Today",
        )
    if follow_up_timing in ("Follow up today", "Follow up urgently"):
        reason = (
            f"No recorded update in {days_since_last_activity} day(s) while in the {status.title()} stage."
            if days_since_last_activity is not None
            else "This application may be ready for a follow-up."
        )
        return NextAction("Follow up with recruiter", reason, "Today")
    return NextAction("Wait", "No urgent action needed right now.", "No rush")


def _compute_follow_up_timing(
    *, status: str, days_since_last_activity: int | None, has_pending_follow_up_task: bool
) -> tuple[str, str]:
    thresholds = FOLLOW_UP_THRESHOLDS.get(status)
    if not thresholds or days_since_last_activity is None:
        return "Not needed", f"No follow-up is typically expected at the {status.replace('_', ' ').title()} stage."
    consider, today, urgent = thresholds
    if has_pending_follow_up_task:
        return "Consider soon", "You already have a follow-up task pending for this application."
    if days_since_last_activity >= urgent:
        return "Follow up urgently", f"No update in {days_since_last_activity} days while in {status.title()} — well past the typical window for this stage."
    if days_since_last_activity >= today:
        return "Follow up today", f"No update in {days_since_last_activity} days while in {status.title()}."
    if days_since_last_activity >= consider:
        return "Consider soon", f"{days_since_last_activity} days since the last update — approaching the typical follow-up window for {status.title()}."
    return "Not needed", f"Only {days_since_last_activity} day(s) since the last update — still within the typical waiting window."


def _compute_risks(
    *, status: str, days_since_last_activity: int | None, deadline_days_left: int | None,
    upcoming_interview: ApplicationInterview | None, overdue_task_count: int, missing_recruiter_contact: bool,
) -> list[Risk]:
    risks: list[Risk] = []
    if status in TERMINAL_STATUSES:
        return risks

    if deadline_days_left is not None and 0 <= deadline_days_left <= DEADLINE_SOON_DAYS:
        risks.append(Risk(
            "Deadline approaching", "high" if deadline_days_left <= DEADLINE_IMMINENT_DAYS else "medium",
            f"The application deadline is in {deadline_days_left} day(s).",
            "Submit or update the application before the deadline.",
        ))
    elif deadline_days_left is not None and deadline_days_left < 0 and status in ("SAVED", "PLANNING_TO_APPLY"):
        risks.append(Risk(
            "Deadline passed", "high", "The deadline for this application has already passed.",
            "Confirm whether this opportunity is still open, or update/close this application.",
        ))

    if days_since_last_activity is not None:
        if days_since_last_activity >= VERY_STALE_DAYS:
            risks.append(Risk(
                "Stale application", "high", f"No activity recorded in {days_since_last_activity} days.",
                "Follow up with the recruiter or decide whether to keep pursuing this application.",
            ))
        elif days_since_last_activity >= STALE_DAYS:
            risks.append(Risk(
                "Application inactive", "medium", f"No activity recorded in {days_since_last_activity} days.",
                "Consider a follow-up to check on the application's status.",
            ))

    if overdue_task_count > 0:
        risks.append(Risk(
            "Overdue task(s)", "high" if overdue_task_count >= 3 else "medium",
            f"{overdue_task_count} task(s) on this application are past their due date.",
            "Review and complete or reschedule the overdue task(s).",
        ))

    if upcoming_interview is not None:
        missing_bits = []
        if upcoming_interview.interview_type in ("VIDEO",) and not upcoming_interview.meeting_url:
            missing_bits.append("meeting link")
        if upcoming_interview.interview_type in ("ONSITE",) and not upcoming_interview.location:
            missing_bits.append("location")
        if missing_bits:
            risks.append(Risk(
                "Missing interview information", "low",
                f"Upcoming interview is missing: {', '.join(missing_bits)}.",
                "Add the missing details to the interview record before it starts.",
            ))

    if missing_recruiter_contact and status in ("INTERVIEW", "OFFER"):
        risks.append(Risk(
            "Missing recruiter contact", "low", "No recruiter name or email is on file for this application.",
            "Add recruiter contact details if you have them, for easier follow-up.",
        ))

    return risks


def _compute_action_plan(
    *, application: Application, status: str, deadline_days_left: int | None,
    upcoming_interview: ApplicationInterview | None, recently_concluded_interview: ApplicationInterview | None,
    overdue_tasks: list[ApplicationTask], follow_up_timing: str, follow_up_reason: str,
) -> list[ActionPlanItem]:
    items: list[ActionPlanItem] = []

    for task in overdue_tasks[:3]:
        items.append(ActionPlanItem(
            "TODAY", f"Complete overdue task: {task.title}", "High",
            f"Was due {task.due_at.strftime('%b %d')}." if task.due_at else "Overdue.",
            due_date=date.today().isoformat(),
        ))

    if status == "SAVED":
        items.append(ActionPlanItem("TODAY", "Review job requirements", "Medium", "Not yet applied."))
        items.append(ActionPlanItem("TODAY", f"Apply to {application.job_title} at {application.company}", "High", "This job is saved but not yet applied to."))
    elif status == "PLANNING_TO_APPLY":
        items.append(ActionPlanItem("TODAY", "Review job requirements", "Medium", "Marked as planning to apply."))

    if deadline_days_left is not None and 0 <= deadline_days_left <= DEADLINE_SOON_DAYS:
        items.append(ActionPlanItem(
            "TODAY" if deadline_days_left <= DEADLINE_IMMINENT_DAYS else "NEXT_2_DAYS",
            "Meet the application deadline", "Critical" if deadline_days_left <= DEADLINE_IMMINENT_DAYS else "High",
            f"Deadline is in {deadline_days_left} day(s).", due_date=application.deadline.isoformat() if application.deadline else None,
        ))

    if status == "ASSESSMENT":
        items.append(ActionPlanItem("NEXT_2_DAYS", "Complete assessment", "High", "This application is waiting on an assessment."))

    if upcoming_interview is not None:
        days_to_interview = (upcoming_interview.scheduled_at.date() - date.today()).days
        interview_label = upcoming_interview.round_name or f"{upcoming_interview.interview_type.title()} interview"
        due = upcoming_interview.scheduled_at.date().isoformat()
        if days_to_interview <= 1:
            items.append(ActionPlanItem("BEFORE_INTERVIEW", "Review your resume", "High", f"{interview_label} is coming up.", due_date=due))
            items.append(ActionPlanItem("BEFORE_INTERVIEW", "Prepare questions for the interviewer", "Medium", f"{interview_label} is coming up.", due_date=due))
        else:
            items.append(ActionPlanItem("NEXT_2_DAYS", f"Prepare for {interview_label}", "High", f"Scheduled for {upcoming_interview.scheduled_at.strftime('%b %d')}.", due_date=due))
            items.append(ActionPlanItem("NEXT_2_DAYS", f"Research {application.company}", "Medium", f"{interview_label} is coming up."))

    if recently_concluded_interview is not None:
        label = recently_concluded_interview.round_name or f"{recently_concluded_interview.interview_type.title()} interview"
        items.append(ActionPlanItem("AFTER_INTERVIEW", "Send a follow-up / thank-you", "High", f"{label} appears to have concluded — its result hasn't been recorded yet."))

    if follow_up_timing in ("Follow up today", "Follow up urgently"):
        items.append(ActionPlanItem("TODAY", "Follow up with the recruiter", "Critical" if follow_up_timing == "Follow up urgently" else "High", follow_up_reason))

    # Bounded output — keep the plan scannable rather than exhaustive.
    return items[:8]


def compute_signals(db: Session, application: Application) -> ApplicationSignals:
    status = application.status
    now = datetime.utcnow()
    today = date.today()

    last_activity_at = _last_activity_at(db, application)
    days_since_last_activity = (now - last_activity_at).days if last_activity_at else None
    deadline_days_left = (application.deadline - today).days if application.deadline else None

    upcoming_interview = _upcoming_interview(db, application.id)
    recently_concluded_interview = _recently_concluded_interview(db, application.id)

    overdue_tasks = list(
        db.scalars(
            select(ApplicationTask)
            .where(
                ApplicationTask.application_id == application.id,
                ApplicationTask.completed.is_(False),
                ApplicationTask.due_at.is_not(None),
                ApplicationTask.due_at < now,
            )
            .order_by(ApplicationTask.due_at.asc())
        )
    )
    overdue_task_count = len(overdue_tasks)
    has_pending_follow_up_task = _has_pending_follow_up_task(db, application.id)
    missing_recruiter_contact = not application.recruiter_name and not application.recruiter_email

    health = _compute_health(
        status=status, days_since_last_activity=days_since_last_activity, deadline_days_left=deadline_days_left,
        upcoming_interview=upcoming_interview, overdue_task_count=overdue_task_count,
        missing_recruiter_contact=missing_recruiter_contact,
    )
    priority = _compute_priority(
        status=status, health=health, deadline_days_left=deadline_days_left,
        upcoming_interview=upcoming_interview, overdue_task_count=overdue_task_count,
    )
    follow_up_timing, follow_up_reason = _compute_follow_up_timing(
        status=status, days_since_last_activity=days_since_last_activity, has_pending_follow_up_task=has_pending_follow_up_task,
    )
    next_action = _compute_next_action(
        status=status, days_since_last_activity=days_since_last_activity, deadline_days_left=deadline_days_left,
        upcoming_interview=upcoming_interview, overdue_task_count=overdue_task_count, follow_up_timing=follow_up_timing,
    )
    risks = _compute_risks(
        status=status, days_since_last_activity=days_since_last_activity, deadline_days_left=deadline_days_left,
        upcoming_interview=upcoming_interview, overdue_task_count=overdue_task_count,
        missing_recruiter_contact=missing_recruiter_contact,
    )
    action_plan = _compute_action_plan(
        application=application, status=status, deadline_days_left=deadline_days_left,
        upcoming_interview=upcoming_interview, recently_concluded_interview=recently_concluded_interview,
        overdue_tasks=overdue_tasks, follow_up_timing=follow_up_timing, follow_up_reason=follow_up_reason,
    )

    return ApplicationSignals(
        application_id=application.id, status=status, days_since_last_activity=days_since_last_activity,
        last_activity_at=last_activity_at, deadline_days_left=deadline_days_left, upcoming_interview=upcoming_interview,
        overdue_task_count=overdue_task_count, has_pending_follow_up_task=has_pending_follow_up_task,
        missing_recruiter_contact=missing_recruiter_contact, health=health, priority=priority, next_action=next_action,
        follow_up_timing=follow_up_timing, follow_up_reason=follow_up_reason, risks=risks, action_plan=action_plan,
    )
