"""V25.1 — one-time, idempotent backfill of `OrganizationMember` rows
for every `Organization` that existed before this version (spec
sections 6, 10, 23, 24: existing recruiter accounts, companies, and
teams must keep working, with a deterministic, documented migration —
never an arbitrary/guessed organization assignment).

What this does, per existing `Organization` row:

    1. If `organization.owner_user_id` is set and has no
       OrganizationMember row yet, create one: role=OWNER,
       status=ACTIVE, joined_at=organization.created_at.
    2. For every `CompanyTeamMember` row on that organization with
       role="member" (role="owner" rows are already covered by step 1
       — see app.api.company._ensure_owner_membership, which always
       keeps an "owner" CompanyTeamMember row in sync with
       owner_user_id), create/update an OrganizationMember row:
       role=RECRUITER, status=ACTIVE.

What this deliberately does NOT do (spec section 23 — "never silently
merge users or companies"):

    - It never invents an organization for a recruiter who has no
      `Organization` row at all (a solo recruiter who never created a
      company profile). Such a recruiter is left exactly as they were
      pre-V25.1 — able to keep working solo (app.core.team_access
      falls back to `{user.id}` for them, unchanged) — and can create
      a real organization at any time via `POST /api/v1/organizations`.
    - It never merges two different recruiters' data into one
      organization, and never assigns government/platform-owned jobs
      (spec section 10) an organization — those have no
      `Organization.owner_user_id` in the first place, so this script
      never touches `jobs` at all; recruiter-owned jobs stay
      associated the same way they always have (`Job.owner_user_id`),
      now indirectly organization-scoped via
      `app.core.team_access.team_owner_ids` reading the freshly
      backfilled `OrganizationMember` rows.

Safe to run multiple times (every insert is guarded by an existence
check first, matching this script's own "idempotent" claim above) and
safe to run against a database that already has some V25.1-native
organizations (created via the new API) mixed in with legacy ones —
those already have an OWNER OrganizationMember row from
`app.api.organizations.create_organization`, so step 1 is a no-op for
them.

Usage:
    python -m scripts.migrate_v25_1_backfill_organizations [--dry-run]
"""

from __future__ import annotations

import sys
from datetime import datetime

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.domain import CompanyTeamMember, Organization, OrganizationMember


def backfill(dry_run: bool = False) -> dict:
    db = SessionLocal()
    stats = {"organizations_scanned": 0, "owner_rows_created": 0, "recruiter_rows_created": 0, "skipped_no_owner": 0}
    try:
        organizations = db.scalars(select(Organization)).all()
        for org in organizations:
            stats["organizations_scanned"] += 1

            if org.owner_user_id is None:
                stats["skipped_no_owner"] += 1
            else:
                existing_owner = db.scalars(
                    select(OrganizationMember).where(
                        OrganizationMember.organization_id == org.id,
                        OrganizationMember.user_id == org.owner_user_id,
                    )
                ).first()
                if existing_owner is None:
                    stats["owner_rows_created"] += 1
                    if not dry_run:
                        db.add(
                            OrganizationMember(
                                organization_id=org.id,
                                user_id=org.owner_user_id,
                                role="OWNER",
                                status="ACTIVE",
                                joined_at=org.created_at or datetime.utcnow(),
                            )
                        )
                elif existing_owner.role != "OWNER" or existing_owner.status != "ACTIVE":
                    # Pre-existing row from a partial/earlier run — make
                    # it correct rather than skipping it silently.
                    if not dry_run:
                        existing_owner.role = "OWNER"
                        existing_owner.status = "ACTIVE"
                        existing_owner.updated_at = datetime.utcnow()

            team_rows = db.scalars(
                select(CompanyTeamMember).where(
                    CompanyTeamMember.company_id == org.id, CompanyTeamMember.role == "member"
                )
            ).all()
            for team_row in team_rows:
                existing = db.scalars(
                    select(OrganizationMember).where(
                        OrganizationMember.organization_id == org.id,
                        OrganizationMember.user_id == team_row.user_id,
                    )
                ).first()
                if existing is None:
                    stats["recruiter_rows_created"] += 1
                    if not dry_run:
                        db.add(
                            OrganizationMember(
                                organization_id=org.id,
                                user_id=team_row.user_id,
                                role="RECRUITER",
                                status="ACTIVE",
                                invited_by=team_row.added_by_user_id,
                                joined_at=team_row.created_at,
                            )
                        )

        if dry_run:
            db.rollback()
        else:
            db.commit()
        return stats
    finally:
        db.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    result = backfill(dry_run=dry)
    print(f"{'[DRY RUN] ' if dry else ''}V25.1 backfill complete: {result}")
    sys.exit(0)
