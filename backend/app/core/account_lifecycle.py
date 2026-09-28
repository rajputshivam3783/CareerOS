"""V25.6 — account deactivation and personal-data erasure.

TWO DIFFERENT THINGS (never conflate them)
-------------------------------------------
Deactivation   ``deactivate_account``   Reversible. The person stops being able to sign in
               and their sessions end. NOTHING is deleted. A platform administrator can
               reactivate the account (``app.core.platform_lifecycle.reactivate_user``).

Erasure        ``erase_account``        Irreversible. The person's *personal data* is removed
               or anonymised. The ``users`` row itself is KEPT (see below) but no longer
               identifies anyone.

WHY THE USER ROW IS ANONYMISED IN PLACE, NOT DELETED
-----------------------------------------------------
Foreign keys point at ``users.id`` from organisation-owned data. ``applicants.user_id`` is
ON DELETE CASCADE - hard-deleting a candidate would silently destroy every recruiter's
hiring record for that person, and ``jobs.owner_user_id`` would be set NULL, hiding the
organisation's jobs from its own team. One person asking to be forgotten must never
delete organisation-wide data (spec section 11), so the row stays, scrubbed:
email/name/phone/company fields cleared, password replaced with an unusable random hash,
account permanently inactive.

WHAT HAPPENS TO EACH KIND OF DATA
---------------------------------
Deleted (the person's own data)   every table with a ``user_id`` (or other ON DELETE CASCADE
                                  user column) except the retained ones below, together with
                                  everything that hangs off those rows: profile, resume and
                                  analyses, personal application tracker (+ uploaded document
                                  files on disk), notifications, email records, AI and Career
                                  Agent conversations, alerts, recommendations, sessions,
                                  refresh tokens, OTP rows, password history, search history.
Scrubbed, record kept             ``applicants`` (the organisation's hiring record): the
                                  candidate's cover note and resume snapshot are removed;
                                  stage, status, dates and the recruiter's decision remain
                                  because the employing organisation has its own legitimate
                                  interest in them.
Kept, membership ended            ``organization_members``: status -> REMOVED (history kept).
Kept, identity removed            ``audit_logs`` / ``platform_audit_logs``: rows are never
                                  deleted here; the actor's email label is replaced. IP
                                  addresses on audit rows are retained as security
                                  telemetry (a documented policy decision - see
                                  docs/DATA_RETENTION_AND_DELETION.md).
Kept, pseudonymous                ``ai_usage_logs`` (user_id only, no prompt text).
Untouched                         jobs, organisations, and other users' data.

Refused (HTTP 409): the user is the ONLY active OWNER of an organisation. Ownership must be
transferred (or the organisation closed) first; otherwise an organisation would be left
ownerless.

The functions here do NOT check authentication; the API layer (app.api.account) re-verifies
the password before calling them.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.core.sessions import revoke_all_sessions
from app.db.base import Base
from app.models.domain import (
    Applicant,
    Application,
    ApplicationDocument,
    AuditLog,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    PlatformAuditLog,
    User,
)

log = logging.getLogger("careeros.account_lifecycle")

ANONYMIZED_EMAIL_DOMAIN = "anonymized.invalid"

# Tables whose rows are never bulk-deleted by erasure (each has its own rule above).
RETAIN_TABLES = frozenset(
    {
        "users",
        "applicants",
        "organization_members",
        "organization_invitations",
        "audit_logs",
        "platform_audit_logs",
        "ai_usage_logs",
    }
)


class AccountLifecycleError(Exception):
    """A lifecycle action was refused for a business reason (mapped to HTTP 409)."""


@dataclass
class ErasureResult:
    deleted_rows: dict[str, int] = field(default_factory=dict)
    document_files_removed: int = 0
    applicant_records_scrubbed: int = 0


def is_anonymized(user: User) -> bool:
    return (user.email or "").endswith("@" + ANONYMIZED_EMAIL_DOMAIN)


def sole_owner_blockers(db: Session, user: User) -> list[dict]:
    """Organisations that would be left with no active OWNER if ``user`` left."""
    org_ids = set(
        db.scalars(
            select(OrganizationMember.organization_id).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.role == "OWNER",
                OrganizationMember.status == "ACTIVE",
            )
        ).all()
    )
    org_ids.update(db.scalars(select(Organization.id).where(Organization.owner_user_id == user.id)).all())

    blockers: list[dict] = []
    for org_id in sorted(org_ids):
        other_owner = db.scalars(
            select(OrganizationMember.id).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.role == "OWNER",
                OrganizationMember.status == "ACTIVE",
                OrganizationMember.user_id != user.id,
            )
        ).first()
        if other_owner is None:
            org = db.get(Organization, org_id)
            blockers.append({"organization_id": org_id, "name": org.name if org else None})
    return blockers


def _raise_if_sole_owner(db: Session, user: User) -> None:
    blockers = sole_owner_blockers(db, user)
    if blockers:
        names = ", ".join(str(b["name"] or b["organization_id"]) for b in blockers)
        raise AccountLifecycleError(
            f"You are the only owner of: {names}. Transfer ownership to another member (or close the "
            "organisation) before deactivating or deleting your account."
        )


def deactivate_account(db: Session, user: User) -> None:
    """Reversible self-service deactivation. Does not commit."""
    from app.core.platform_lifecycle import deactivate_user

    _raise_if_sole_owner(db, user)
    deactivate_user(db, user, reason="self_requested")
    revoke_all_sessions(db, user)


# ---------------------------------------------------------------------------
# Erasure
# ---------------------------------------------------------------------------


def _erasure_columns():
    """(table, column) pairs whose rows belong solely to the person being erased."""
    for table in Base.metadata.sorted_tables:
        if table.name in RETAIN_TABLES:
            continue
        for col in table.c:
            fks = list(col.foreign_keys)
            targets_users = any(fk.column.table.name == "users" for fk in fks)
            if targets_users:
                if all((fk.ondelete or "").upper() != "SET NULL" for fk in fks if fk.column.table.name == "users"):
                    yield table, col
            elif col.name == "user_id" and not fks:
                yield table, col  # a plain user_id column with no FK still holds personal data


def _delete_where(db: Session, table, where_clause, counts: dict[str, int], _seen: frozenset = frozenset()) -> None:
    """Delete rows of ``table`` matching ``where_clause`` after first deleting every row in
    any table that references them (foreign keys), so nothing is orphaned regardless of
    whether the database or the ORM would have cascaded."""
    if table.name in _seen:  # defensive: a self/cyclic reference must not recurse forever
        return
    seen = _seen | {table.name}
    pk_cols = list(table.primary_key.columns)
    if len(pk_cols) == 1:
        ids = select(pk_cols[0]).where(where_clause)
        for child in Base.metadata.sorted_tables:
            if child is table or child.name in RETAIN_TABLES:
                continue
            for fk in child.foreign_keys:
                if fk.column.table is table:
                    _delete_where(db, child, fk.parent.in_(ids), counts, seen)
    result = db.execute(delete(table).where(where_clause))
    if result.rowcount:
        counts[table.name] = counts.get(table.name, 0) + result.rowcount


def _document_files_for(db: Session, user_id: int) -> list[str]:
    return list(
        db.scalars(
            select(ApplicationDocument.stored_filename)
            .join(Application, Application.id == ApplicationDocument.application_id)
            .where(Application.user_id == user_id)
        ).all()
    )


def _remove_document_files(names: list[str]) -> int:
    base = Path(settings.application_document_storage_dir)
    removed = 0
    for name in names:
        if not name or name != Path(name).name:  # never follow a path out of the storage directory
            continue
        try:
            path = base / name
            if path.is_file():
                path.unlink()
                removed += 1
        except OSError:
            log.warning("Could not remove a stored document file during erasure", exc_info=True)
    return removed


def erase_account(db: Session, user: User) -> ErasureResult:
    """Irreversibly erase/anonymise ``user``'s personal data (see module docstring).

    Commits its own transaction (all-or-nothing), then removes document files from disk.
    Idempotent: erasing an already-anonymised account is a no-op returning an empty result."""
    result = ErasureResult()
    if is_anonymized(user):
        return result

    _raise_if_sole_owner(db, user)

    user_id = user.id
    original_email = user.email
    placeholder_email = f"deleted-user-{user_id}@{ANONYMIZED_EMAIL_DOMAIN}"
    placeholder_label = f"deleted-user-{user_id}"

    files = _document_files_for(db, user_id)

    # 1. The person's own data (children first).
    for table, column in _erasure_columns():
        _delete_where(db, table, column == user_id, result.deleted_rows)

    # 2. Organisation-owned hiring records: keep the record, drop the personal content.
    scrubbed = db.execute(
        update(Applicant).where(Applicant.user_id == user_id).values(cover_note=None, resume_snapshot=None)
    )
    result.applicant_records_scrubbed = scrubbed.rowcount or 0

    # 3. End organisation memberships (history kept) and revoke invitations sent to this address.
    db.execute(
        update(OrganizationMember)
        .where(OrganizationMember.user_id == user_id, OrganizationMember.status != "REMOVED")
        .values(status="REMOVED", updated_at=datetime.utcnow())
    )
    db.execute(
        update(OrganizationInvitation)
        .where(OrganizationInvitation.email == (original_email or "").strip().lower())
        .values(status="REVOKED", email=placeholder_email)
    )

    # 4. Audit trail is kept; the identity on it is removed.
    # SessionLocal uses autoflush=False, so the ACCOUNT_ERASED audit row added by the caller is still
    # pending here; flush it so the scrub below also covers it (otherwise it is inserted afterwards with
    # the original email as actor_label).
    db.flush()
    db.execute(
        update(AuditLog).where(AuditLog.actor_id == str(user_id)).values(actor_label=placeholder_label)
    )
    db.execute(
        update(AuditLog)
        .where(AuditLog.entity_type == "user", AuditLog.entity_id == original_email)
        .values(entity_id=placeholder_label)
    )
    db.execute(
        update(PlatformAuditLog).where(PlatformAuditLog.actor_user_id == user_id).values(actor_label=placeholder_label)
    )

    # 5. The account row itself: no longer identifies anyone, can never sign in.
    user.email = placeholder_email
    user.full_name = "Deleted user"
    user.phone = None
    user.company_name = None
    user.company_website = None
    user.company_email = None
    user.password_hash = hash_password(secrets.token_urlsafe(48))  # valid hash nobody knows
    user.email_verified = False
    user.active = False
    user.account_status = "DEACTIVATED"
    user.suspended_at = datetime.utcnow()
    user.suspension_reason = "account_erased"
    db.add(user)
    db.commit()

    result.document_files_removed = _remove_document_files(files)
    return result
