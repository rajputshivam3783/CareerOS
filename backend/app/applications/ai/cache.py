"""V22.4 — content-hash cache for AI Application Intelligence outputs.

Exact same pattern as app.resume_ai.cache, just keyed by
application_id instead of user_id (an application already belongs to
exactly one user, enforced upstream by
app.applications.service.get_application, so no separate ownership
column is needed here — see ApplicationAIInsight's own docstring).
Same inputs -> same context_key -> cache hit -> zero additional
provider calls, which is both the cost control spec section 17 asks
for and the cache-invalidation strategy spec section 12 asks for: a
status change, new interview, task change, or deadline edit changes
``ApplicationSignals.fingerprint()``, which changes the context_key,
which naturally "invalidates" the old entry by simply not matching it
— there is no separate invalidation step to get wrong.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.domain import ApplicationAIInsight


def make_context_key(kind: str, fingerprint: dict, *extra: str) -> str:
    parts = [kind, json.dumps(fingerprint, sort_keys=True, default=str), *extra]
    joined = "\u241f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def get_cached(db: Session, *, application_id: int, kind: str, context_key: str) -> ApplicationAIInsight | None:
    return db.scalar(
        select(ApplicationAIInsight)
        .where(
            ApplicationAIInsight.application_id == application_id,
            ApplicationAIInsight.kind == kind,
            ApplicationAIInsight.context_key == context_key,
        )
        .order_by(ApplicationAIInsight.created_at.desc())
        .limit(1)
    )


def store(
    db: Session, *, application_id: int, kind: str, context_key: str, content: dict,
    provider: str | None, model: str | None, degraded: bool,
) -> ApplicationAIInsight:
    """V23.5 fix (docs/V23_BUG_REPORT.md): two rapid requests for the
    same (application_id, kind, context_key) — a double-click, a retry,
    or simply two requests landing close enough together, as
    test_ai_generate_endpoints_are_rate_limited's rapid-fire calls do —
    can both miss get_cached() above and both reach this insert. The
    UNIQUE constraint on ApplicationAIInsight correctly stops the
    second row from being written, but a bare `db.commit()` let that
    surface as an uncaught IntegrityError (a 500 to a user whose
    request was, semantically, a cache hit once the first request
    finished). Same get-or-return-existing pattern used everywhere else
    in this codebase a concurrent insert can race a unique constraint
    (e.g. app.job_alerts.execution._record_delivery): the loser of the
    race rolls back and returns the winner's row instead of raising.
    """
    row = ApplicationAIInsight(
        application_id=application_id, kind=kind, context_key=context_key,
        content_json=json.dumps(content), provider=provider, model=model, degraded=degraded,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_cached(db, application_id=application_id, kind=kind, context_key=context_key)
        if existing is not None:
            return existing
        raise  # constraint violation for a reason other than a same-key race — don't swallow it
    db.refresh(row)
    return row


def content_of(row: ApplicationAIInsight) -> dict:
    return json.loads(row.content_json)
