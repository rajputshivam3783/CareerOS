# V25.1 — Multi-Tenant Architecture & Organization Management

Phase one of V25: a secure, scalable multi-tenant organization layer,
additive on top of every V1–V24 feature. **V25.2 is explicitly out of
scope for this pass.**

## Architecture

```
Platform
    └── Organization                 (organizations — extended, not replaced)
            └── OrganizationMember    (NEW — role + status per user)
                    └── (a member's) Jobs → Applications → Candidates
```

Candidates remain platform users and are never made organization
members by anything in this pass.

### Why this builds on an existing table instead of a parallel one

CareerOS already had an `Organization` table (V18.1 — a recruiter's
"Company" profile: name, slug, description, logo, website, industry,
company_size, location, `owner_user_id`, timestamps) and a
`CompanyTeamMember` roster (V18.4 — owner/member roles, instant-add by
email, no invitation flow). Spec section 2's "Organization Model" is,
field for field, that same table. Building a second, parallel
`organizations` table would have meant two sources of truth for what a
company profile is — exactly the kind of duplication the brief
elsewhere explicitly warns against ("do not create a duplicate email
system"). Instead, V25.1:

- **Extends** `Organization` with two new nullable/defaulted columns:
  `created_by` (historical record only — see below) and `is_active`
  (the soft-deletion flag spec section 2 asks for).
- **Adds** a new `OrganizationMember` table with real roles
  (OWNER/ADMIN/RECRUITER) and states (PENDING/ACTIVE/SUSPENDED/REMOVED),
  which `CompanyTeamMember` never had (it only has "owner"/"member",
  no suspension, no invitation).
- **Keeps `CompanyTeamMember` and every V18.1–V18.7 endpoint that reads
  it completely unmodified.** The two owner-only "instant add" team
  endpoints (`POST/DELETE /recruiter/company/team/...`) now also
  mirror each write into `OrganizationMember`
  (`app.core.organizations.sync_legacy_membership`), so a recruiter who
  never touches the new API still gets correct, isolated org-scoped
  access.

### Ownership

`Organization.owner_user_id` (V18.1) and `Organization.created_by`
(new, V25.1) are both **historical facts, never used for
authorization**. The authoritative owner is whoever holds the
`OrganizationMember` row with `role=OWNER, status=ACTIVE` for that
organization (spec section 4). `POST /api/v1/organizations` creates
the organization row and its OWNER membership in one transaction
(`db.flush()` to get the new id, then a single `db.commit()` — every
failure before that commit rolls back everything, so a partially
created organization can never exist).

An organization can never become ownerless:
`app.core.organizations.ensure_not_last_owner` blocks removing,
suspending, or role-changing-away-from-OWNER the organization's sole
remaining active OWNER. Ownership *transfer* (promote someone else to
OWNER, then the original owner steps down — two separate, already-
supported API calls) works today; a single dedicated "transfer
ownership" endpoint was judged out of scope for this pass and is not
implemented — see Known Limitations.

## Membership & Roles

`OrganizationMember` has exactly one row per `(organization_id,
user_id)` ever — enforced by a plain `UniqueConstraint`, which is what
satisfies "no duplicate active membership" (spec section 3) portably
across SQLite (dev/test) and PostgreSQL (prod) without a
partial/filtered unique index, whose syntax differs between the two.
Re-inviting someone who was REMOVED reactivates their existing row
rather than inserting a second one.

| Role | Can do |
|---|---|
| **OWNER** | Everything ADMIN can, plus: grant/revoke OWNER or ADMIN role, remove/suspend an ADMIN or OWNER, transfer-adjacent actions |
| **ADMIN** | Manage organization settings, invite/suspend/remove/re-role a RECRUITER (never an OWNER; never grants ADMIN/OWNER), view members/analytics/audit log |
| **RECRUITER** | View organization/members, manage their authorized jobs/candidates/pipeline (via the existing `app.api.recruiter*` routes, now organization-scoped — see below) |

Permission checks are explicit sets (`app.core.organizations.can_manage_role`),
never a numeric role comparison for *who can manage whom* — the same
reasoning `app.core.rbac`'s `ROLE_HIERARCHY` docstring already gives
for platform roles applies here: a hierarchy bug should never be able
to silently widen what a role can do. (A numeric rank is used in
exactly one place — `require_organization_role`'s "does this role meet
the *minimum* required tier" check for read-style access — which is a
safe use of ranking because it can only ever require *more*, not
grant *more*.)

## Authorization Model (spec sections 8, 12, 21 — the most important part)

**The authenticated user's ACTIVE `OrganizationMember` row is the only
thing that ever grants access.** Every organization-scoped route
depends on one of `app.core.organizations.require_organization_membership`
/ `require_organization_role` / `require_organization_admin` /
`require_organization_owner`, which:

1. Take `organization_id` from the URL path only.
2. Look up the organization and the caller's membership fresh from the
   database on every request — nothing about role or org membership is
   ever read from a client-supplied header, query param, or body field.
3. Return **404** (not 403) when the caller has no ACTIVE membership —
   so probing a cross-tenant ID can't even distinguish "wrong role"
   from "doesn't exist," matching this codebase's existing convention
   (see `app.api.company._owned_company_or_404`).

A platform `admin`/`super_admin` role has **no implicit backdoor** into
organization-scoped endpoints — organization access is membership-only
(see `test_platform_admin_has_no_implicit_backdoor_into_org_endpoints`).
Platform admins retain their separate, pre-existing `/api/v1/admin/*`
oversight endpoints, untouched by this pass.

### How tenant isolation reaches jobs/candidates/pipeline/analytics/AI

Rather than adding an `organization_id` filter to every recruiter route
individually (spec section 9 explicitly warns against blindly adding
`organization_id` to every table), V25.1 updates the single existing
chokepoint every one of those routes already filters through:
`app.core.team_access.team_owner_ids(db, user)`, consumed by
`app.api.recruiter`, `app.api.recruiter_candidates`,
`app.api.recruiter_analytics`, and `app.api.resume_ai` (the AI path —
this is also spec section 27's audit: no recruiter-facing AI call can
see another organization's data, because none of them ever see another
organization's `Job`/`Application` rows to send to a provider in the
first place). That function now resolves the caller's ACTIVE
`OrganizationMember` set first, falling back to the legacy
`Organization.owner_user_id`/`CompanyTeamMember`-only resolution only
for an organization that predates V25.1 and hasn't been backfilled yet.
This is a strictly *narrower*, more correct result wherever it applies
(SUSPENDED/REMOVED members are now correctly excluded, which the
legacy table had no way to express) — never a wider one, so no
existing recruiter loses access they had before.

`Job`, `Application`, and other recruiter resources were **not**
migrated to a new `organization_id` foreign key in this pass (spec
section 9/11): `Job.owner_user_id` plus the org-aware
`team_owner_ids` above already gives correct, enforced isolation, and
`Job.organization_id` (which already exists!) points at
`government_organizations`, a completely unrelated table for
platform-owned government postings — reusing that column for a
different foreign key would have been a breaking, ambiguous schema
change. See Known Limitations for what this scoping choice does and
doesn't cover.

## Invitations (spec sections 15, 16)

`OrganizationInvitation` stores a SHA-256 hash of a
`secrets.token_urlsafe(32)` token — never the raw token — the same
pattern as `User.password_hash`. The raw token is returned exactly
once, in the `POST .../members/invite` response body (for the
inviting admin to copy/share) and inside the invitation email; it is
never logged and never persisted anywhere in recoverable form.

- Expire after 7 days (`expires_at`, enforced server-side on accept).
- Single-use: accepting sets `status=ACCEPTED`; a second accept
  attempt with the same token is rejected.
- Revocable: inviting the same email again while a PENDING invitation
  exists for that org auto-revokes the earlier one first.
- **Explicit acceptance only.** A matching email is necessary but
  never sufficient: `POST /api/v1/organization-invitations/{token}/accept`
  requires the logged-in user's own email to match the invitation's
  email *and* the correct token — so a forwarded/leaked link can't be
  used to join under a different account, and simply having an account
  with the invited address is never enough by itself.

Delivery reuses the existing V23.2 email queue
(`app.email.service.queue_email`) with a new `ORGANIZATION_INVITATION`
system template — no parallel email system was built. See Known
Limitations for the one gap this reuse creates.

## Audit Log

No new `organization_audit_logs` table was created. Every
organization-management action (`create`, `settings_changed`,
`member_invited`, `invitation_accepted`, `invitation_rejected`,
`member_suspended`, `member_removed`, `member_role_changed`) is written
to the existing platform-wide `audit_logs` table via
`app.core.audit.log_audit` — `entity_type="organization"`,
`entity_id=<organization id>`, `detail=` a small JSON blob with
`target_type`/`target_id`/action-specific metadata. This reuses actor/
request-id/IP attribution that table already gets for free from every
authenticated request (`app.core.security.current_user` sets the actor
context), instead of duplicating that machinery for a second table.
`GET /api/v1/organizations/{id}/audit-log` (OWNER/ADMIN only) reads
from it filtered to that organization.

## API Endpoints (all under `/api/v1`, new — nothing pre-existing changed)

| Method | Path | Access |
|---|---|---|
| POST | `/organizations` | any approved recruiter |
| GET | `/organizations` | any authenticated user (returns their own memberships) |
| GET | `/organizations/{id}` | ACTIVE member |
| PATCH | `/organizations/{id}` | OWNER/ADMIN |
| GET | `/organizations/{id}/members` | ACTIVE member |
| POST | `/organizations/{id}/members/invite` | OWNER/ADMIN |
| POST | `/organization-invitations/{token}/accept` | the invited user |
| POST | `/organization-invitations/{token}/reject` | the invited user |
| POST | `/organizations/{id}/members/{member_id}/suspend` | OWNER/ADMIN |
| DELETE | `/organizations/{id}/members/{member_id}` | OWNER/ADMIN |
| PATCH | `/organizations/{id}/members/{member_id}/role` | OWNER/ADMIN (role rules in `can_manage_role`) |
| GET | `/organizations/{id}/audit-log` | OWNER/ADMIN |

## Data Migration (spec sections 10, 23, 24)

`migrations/v25_1_multi_tenant_organizations.sql` — Postgres
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT
EXISTS`, matching this project's existing migration style; SQLite
dev/test gets the same schema automatically from the ORM models via
`Base.metadata.create_all()` (no change to that mechanism).

`scripts/migrate_v25_1_backfill_organizations.py` — a one-time,
idempotent script (supports `--dry-run`) that creates the matching
`OrganizationMember` row for every pre-existing `Organization.owner_user_id`
(OWNER/ACTIVE) and `CompanyTeamMember` row (RECRUITER/ACTIVE). It never
invents an organization for a solo recruiter who has none, never
merges two recruiters' data, and never touches `jobs` or government/
platform-owned postings at all (see the script's own docstring for the
full reasoning). Run it once, any time after the schema migration,
before or after real traffic — it's additive and safe to re-run.

## Security Considerations / What Was Tested

`tests/test_v25_1_multi_tenant_organizations.py` (8 tests) covers:
atomic organization+OWNER creation; invite→accept, including
wrong-account and reused-token rejection; ADMIN unable to escalate to
OWNER, unable to manage an OWNER, unable to remove the last OWNER;
cross-tenant isolation on GET/PATCH/members/invite/audit-log (all fail
closed as 404); invitation expiry; the legacy `/recruiter/company/team/*`
endpoints continuing to work and populating `OrganizationMember`; and a
platform-admin account confirmed to have no implicit access to another
organization's data.

**NOT VERIFIED:** this authoring sandbox has no outbound network
access, so `pip install -r requirements.txt` cannot succeed and the
test suite (new and pre-existing) could not actually be executed,
matching the same documented limitation in V23.3/V23.4/V24.1/V24.2's
release notes. Every new and modified file was checked with
`python -m py_compile` (no syntax errors) and reviewed by hand against
the exact fixture pattern `tests/test_v18_6_team_access.py` already
uses successfully in this codebase, but "compiles and reads correctly"
is not the same as "passed." Whoever runs this in an environment with
dependencies installed should run:

```
pytest tests/test_v25_1_multi_tenant_organizations.py -v
pytest  # full regression suite
```

before deploying, and treat any failure as a real bug report, not a
sandbox artifact.

## Known Limitations

- **Invitations to an email with no CareerOS account yet create the
  invitation row but do not send an email.** `app.email.service.queue_email`
  requires a real `user_id` (`EmailMessage.user_id` is `NOT NULL`), so
  today an invite is only actually emailed when the invitee already
  has an account. The invitation still exists and can be accepted once
  they register and log in with the matching email — only the email
  notification is deferred. Fixing this properly (e.g. relaxing that
  NOT NULL constraint, or a separate non-user-linked send path) touches
  stable V23.2 schema/infrastructure and was judged out of scope for a
  V25.1-only pass; flagging it here rather than silently working around
  it with a schema change to a different version's stable table.
- **No dedicated "transfer ownership" endpoint.** The same result is
  reachable today via two existing calls (promote a member to OWNER,
  then have the original owner's role changed by the new OWNER, or
  removed once no longer sole owner) but isn't atomic across both
  steps. Spec section 4 explicitly scoped a dedicated transfer flow as
  optional for this phase.
- **`Job`/`Application` rows are not directly tagged with an
  `organization_id`.** Isolation is enforced through
  `team_owner_ids` (see above), which is correct and enforced
  server-side, but means there is no single indexed `WHERE
  organization_id = ?` query available for, e.g., a future
  cross-organization platform report — that would need a real
  `Job.owner_organization_id` migration, deferred to a later phase to
  avoid conflating with the already-occupied `Job.organization_id`
  (government) column.
- Organization logo upload isn't wired to the existing file-upload
  infrastructure — `logo_url` is a plain string field, matching how
  `Organization.logo_url` (V18.1) already worked.
