"""V25.3 — runs the data-quality rule catalog (spec section 13).

Generic over ``rules.RULES``: counting, severity rollup, pagination
and triage-state joining are implemented once here, so a new rule is
one declarative entry in ``rules.py`` and nothing else.

READ-ONLY
---------
Nothing in this module modifies an inspected row. The only write it
performs is to ``data_quality_issue_states`` — an administrator's own
triage decision ("acknowledged", "resolved", "wont_fix") with an
optional note. That is the "explicit safe workflow" section 13 asks
for: a human records a judgement, the underlying data is untouched,
and every state change is written to the V25.2 platform audit trail
by the API layer.

There is deliberately no bulk-fix, auto-repair or "clean up" action
anywhere in the data-quality feature.

COST
----
The summary runs one ``COUNT`` per rule (currently ~16 indexed
counts), not one full scan per rule, and never materializes offending
rows. Rows are only loaded when an administrator opens a single rule,
and then only one bounded page of them.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.intelligence.quality import rules as rules_mod
from app.models.domain import DataQualityIssueState, Job

SEVERITY_ORDER = {severity: index for index, severity in enumerate(rules_mod.SEVERITIES)}

TRIAGE_STATES = ("open", "acknowledged", "resolved", "wont_fix")


def _count(db: Session, rule: rules_mod.QualityRule) -> int:
    statement = rule.statement()
    return int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)


def summary(db: Session, *, entity_type: str | None = None, severity: str | None = None) -> dict:
    """Every rule with its current count, newest issues first.

    Rules that currently find nothing are still listed, with a count
    of zero. A clean rule disappearing from the report would make
    "we stopped checking" and "there is nothing wrong" look the same.
    """
    rows = []
    for rule in rules_mod.RULES:
        if entity_type and rule.entity_type != entity_type:
            continue
        if severity and rule.severity != severity:
            continue
        count = _count(db, rule)
        rows.append({**rule.as_dict(), "count": count, "remediation_supported": True})

    duplicates = duplicate_summary(db)
    rows.sort(key=lambda row: (SEVERITY_ORDER.get(row["severity"], 99), -row["count"]))

    totals: dict[str, int] = {severity_name: 0 for severity_name in rules_mod.SEVERITIES}
    for row in rows:
        totals[row["severity"]] = totals.get(row["severity"], 0) + row["count"]

    return {
        "generated_at": datetime.utcnow(),
        "rules": rows,
        "issues_by_severity": totals,
        "total_issues": sum(totals.values()),
        "duplicate_jobs": duplicates,
        "triage_states": list(TRIAGE_STATES),
        "note": (
            "Data quality checks are read-only. No endpoint in this feature modifies an "
            "inspected record; administrators record a triage decision instead."
        ),
    }


def duplicate_summary(db: Session, *, limit: int = 25) -> dict:
    """Possible duplicate listings, grouped (see rules.duplicate_job_groups_statement)."""
    statement = rules_mod.duplicate_job_groups_statement()
    groups = db.execute(statement.limit(limit)).all()
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    return {
        "rule_id": "job_possible_duplicate",
        "entity_type": "job",
        "severity": "medium",
        "title": "Possible duplicate job listings",
        "description": (
            "Two or more published or in-review jobs share both a title and an organization. "
            "This is a review signal, not a determination — different intakes of the same role "
            "can legitimately look identical."
        ),
        "remediation": "Review the group and reject or close the redundant listing(s) manually.",
        "count": total,
        "groups": [
            {
                "title": title,
                "organization": organization,
                "occurrences": int(occurrences),
                "first_job_id": int(first_job_id),
            }
            for title, organization, occurrences, first_job_id in groups
        ],
    }


def issues(db: Session, rule_id: str, *, limit: int = 25, offset: int = 0) -> dict:
    """One page of the rows a single rule flags.

    Returns identifying labels only — a job id and title, or an
    account id and email. No rule returns resume text, application
    content, private notes, or any profile field beyond the presence
    or absence the rule is about.
    """
    rule = rules_mod.RULES_BY_ID.get(rule_id)
    if rule is None:
        return {}

    statement = rule.statement()
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = db.scalars(statement.limit(limit).offset(offset)).all()

    entity_ids = [getattr(row, rule.id_attr) for row in rows]
    states = _states_for(db, rule_id, entity_ids)

    return {
        **rule.as_dict(),
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": [
            {
                "entity_id": getattr(row, rule.id_attr),
                "label": rule.label(row),
                "triage": states.get(getattr(row, rule.id_attr), {"state": "open", "note": None, "updated_at": None}),
            }
            for row in rows
        ],
    }


def _states_for(db: Session, rule_id: str, entity_ids: list[int]) -> dict[int, dict]:
    """Triage state for a page of entities, in one query (not per row)."""
    if not entity_ids:
        return {}
    rows = db.scalars(
        select(DataQualityIssueState).where(
            DataQualityIssueState.rule_id == rule_id,
            DataQualityIssueState.entity_id.in_(entity_ids),
        )
    ).all()
    return {
        row.entity_id: {
            "state": row.state,
            "note": row.note,
            "updated_at": row.updated_at,
            "updated_by_user_id": row.updated_by_user_id,
        }
        for row in rows
    }


def set_triage_state(
    db: Session,
    *,
    rule_id: str,
    entity_id: int,
    state: str,
    note: str | None,
    actor_user_id: int | None,
) -> DataQualityIssueState:
    """Record an administrator's triage decision.

    Upserts one row per (rule_id, entity_id). Does not commit — the
    API layer commits it together with the platform audit record, so
    a triage decision and its audit entry land in one transaction or
    not at all.
    """
    row = db.scalar(
        select(DataQualityIssueState).where(
            DataQualityIssueState.rule_id == rule_id,
            DataQualityIssueState.entity_id == entity_id,
        )
    )
    if row is None:
        row = DataQualityIssueState(rule_id=rule_id, entity_id=entity_id)
        db.add(row)
    row.state = state
    row.note = (note or None)
    row.updated_by_user_id = actor_user_id
    row.updated_at = datetime.utcnow()
    db.flush()
    return row


def entity_type_of(rule_id: str) -> str | None:
    rule = rules_mod.RULES_BY_ID.get(rule_id)
    return rule.entity_type if rule else None


def missing_skill_mappings(db: Session, *, limit: int = 25) -> dict:
    """Skill names on jobs that the V20.5 catalog does not recognize.

    Reported as a data-quality issue rather than fixed automatically:
    the remedy is an admin adding a canonical skill or an alias
    through the existing V20.5 skill-catalog endpoints, which is a
    judgement about vocabulary, not a repair a script should make.
    """
    from app.intelligence import skills as skills_mod

    jobs = list(
        db.scalars(
            select(Job).where(Job.status == "published", Job.skills.isnot(None)).order_by(Job.id.desc()).limit(1000)
        ).all()
    )
    corpus = skills_mod.build(db, jobs)
    rows = skills_mod.unrecognized_report(corpus, limit=limit)
    return {
        "rule_id": "skill_missing_catalog_mapping",
        "entity_type": "skill",
        "severity": "low",
        "title": "Job skill names not in the skill catalog",
        "description": (
            "These names appear in job skill lists but resolve to no canonical skill or alias, "
            "so they are excluded from every skill analytic."
        ),
        "remediation": (
            "Add a canonical skill or an alias through the skill catalog admin endpoints if the "
            "name is a real skill; otherwise correct the job."
        ),
        "jobs_sampled": len(jobs),
        "count": len(corpus.unrecognized),
        "results": rows,
    }
