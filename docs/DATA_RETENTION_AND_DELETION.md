# Data Inventory, Retention, Deletion & Organization Lifecycle

> This is an engineering document, not legal advice, and not a compliance claim. Retention
> periods below are **defaults chosen by engineering**; your legal/compliance owner must
> confirm them before production (NOT VERIFIED). Nothing is deleted automatically unless you
> opt in (`RETENTION_PURGE_ENABLED=true` **and** you run the purge).

## 1. What personal and business data CareerOS holds

| Category | Where | Notes / minimisation |
|---|---|---|
| Account & authentication | `users`, `user_sessions`, `refresh_tokens`, `email_verifications`, `password_history` | passwords Argon2id-hashed; OTP and refresh tokens stored hashed only; sessions hold IP + user-agent |
| Candidate profile | `profiles`, `resumes`, resume analyses/matches | skills, locations, qualifications. **Sensitive, optional, self-declared:** `date_of_birth`, `reservation_category`, `is_pwd`. |
| Candidate activity | `applications` (private tracker) + notes/tasks/interviews/documents, `saved_jobs`, alerts, notifications, recommendation/behaviour signals, search history | private to the owner |
| Uploaded files | disk volume `var/uploads/application_documents` (`uuid.ext`), DB rows in `application_documents` | `/resume` uploads are parsed to text and only the extracted text + original filename are stored (verified in `app/api/platform.py`); the original bytes are not kept |
| Hiring records (organization-owned) | `applicants`, pipeline history, interviews, offers, recruiter notes, `jobs` | belong to the employing organization; contain candidate cover note + resume snapshot |
| Recruiter/organization data | `organizations`, `organization_members`, `organization_invitations`, company profile/branches/team | invitation rows hold the invitee's email |
| Communications | `email_messages` (recipient, subject, status; **never OTP values**), `notification_*` | |
| AI data | AI conversations/messages, Career Agent conversations and `career_agent_actions`, `ai_usage_logs` | usage logs carry token counts/cost/latency, **no prompt or response text** |
| Audit & security | `audit_logs`, `platform_audit_logs` | actor id/label, action, target, request id, IP |
| Analytics | derived at query time from the tables above | no separate warehouse |

**Protected characteristics.** CareerOS does not collect race, ethnicity, religion, caste,
gender, sexual orientation, marital status, health or political information. The three
sensitive profile fields above exist solely for the candidate-facing government-exam
eligibility calculation (`app/services/eligibility.py`: age relaxation for reserved categories
and persons with disability, as official notifications define). A code search in V25.6 found
**no other reader** of these fields: not recommendation/ranking features, not recruiter
candidate search, not recruiter analytics, not any AI prompt builder, not any serializer that
dumps `Profile` columns. They are removed on account erasure.
Recruiter AI prompts forbid using or inferring protected characteristics and an output filter
withholds text that mentions them or issues a hire/reject decision
(`app/recruiter_analytics/ai.py`). The platform never auto-rejects, auto-advances or
auto-hires: recruiters make every status change.

## 2. Retention policy

"Configurable" = a setting in `app/core/config.py` / `.env`; `0` = keep forever.

| Data | Default retention | Why | Configurable | Deletion behaviour |
|---|---|---|---|---|
| User account (active) | while the account exists | needed to provide the service | â€” | deactivation (reversible) or erasure (Â§3) |
| Consumed/expired OTP rows, revoked/expired refresh tokens | 30 days after creation | short forensic window; contain no plaintext secrets | `RETENTION_AUTH_ARTIFACTS_DAYS` | purge job (opt-in) |
| User sessions | kept (revoked rows remain) | device history shown to the user; low volume | not purged in V25.6 | removed on erasure |
| Read/archived notifications | 365 days | convenience feed; unread never purged | `RETENTION_NOTIFICATIONS_DAYS` | purge job (opt-in) |
| Email delivery records | 365 days | delivery troubleshooting | `RETENTION_EMAIL_MESSAGES_DAYS` | purge job (opt-in) |
| AI usage/cost logs | 365 days | cost reporting | `RETENTION_AI_USAGE_LOGS_DAYS` | purge job (opt-in) |
| Career Agent / AI conversations & actions | until the user's account is erased | the user's own history; not purged automatically | **not configurable in V25.6** (gap) | removed on erasure |
| Candidate private applications & documents | until the candidate deletes them or erases the account | the candidate's own records | user-driven | file removed from disk on delete/erasure |
| Hiring records (`applicants`, pipeline, interviews, offers) | **never purged automatically** | the employing organization's record of a hiring process; retention duration is a business/legal decision (varies by jurisdiction) | not automated â€” **operator decision required** | candidate erasure scrubs cover note + resume snapshot but keeps the record; a job with applicants cannot be deleted |
| Jobs and organizations | never purged automatically | operational/historical | â€” | suspended/deactivated, not deleted (Â§4) |
| Audit logs & security events | **never purged by CareerOS** | accountability; investigation | not automated â€” operator decision required | erasure replaces the actor label only; rows remain |
| Backups | **NOT VERIFIED** | deployment-owned | â€” | erased personal data persists in backups until they expire |

Run the purge: `python backend/scripts/retention_purge.py` (dry run) and `--execute`
(requires `RETENTION_PURGE_ENABLED=true`). Schedule it outside the web process. The purge is
**not wired into the scheduler** in V25.6 and was **not executed** (NOT VERIFIED).

## 3. Account deactivation vs data erasure

Implemented in `app/core/account_lifecycle.py`, exposed at `POST /api/v1/account/deactivate`
and `POST /api/v1/account/delete` (`app/api/account.py`). Both require the current password
(a stolen access token is not enough), are rate limited (5 per 5 minutes per IP), record a
security event, and are unavailable to platform admin accounts.

| | Deactivation | Erasure |
|---|---|---|
| Reversible | yes â€” a platform admin reactivates (`POST /admin/users/{id}/reactivate`) | **no** |
| Sign-in | blocked, all sessions revoked | blocked forever (unusable random password hash) |
| Personal data | untouched | removed / anonymised (below) |
| Confirmation | password | password **and** typing `DELETE MY ACCOUNT` |
| Refused when | user is the only active OWNER of an organization (409) | same |

**Erasure behaviour**

* **Deleted** (every table with a `user_id`, or another cascade-to-user column, except the
  retained ones; child rows first): profile, resume + analyses, private applications with
  notes/tasks/interviews/documents (files removed from disk after the transaction commits),
  notifications, email records, AI and Career Agent conversations/actions, alerts,
  recommendations and behaviour signals, sessions, refresh tokens, OTP rows, password history,
  search history, legacy team links.
* **Scrubbed, record kept:** `applicants` â€” `cover_note` and `resume_snapshot` set to NULL;
  stage/status/dates/decision remain (organization's hiring record).
* **Kept, membership ended:** `organization_members` rows â†’ `REMOVED`.
  Invitations addressed to the user's email â†’ `REVOKED`, email replaced.
* **Kept, identity removed:** audit rows â€” actor label replaced with `deleted-user-<id>`,
  rows where the login-failure target was the email replaced. **IP addresses on audit rows are
  retained** as security telemetry (a policy decision for your legal owner to confirm).
* **Kept, pseudonymous:** `ai_usage_logs` (user id only).
* **The `users` row is kept** but anonymised: email `deleted-user-<id>@anonymized.invalid`,
  name `Deleted user`, phone/company fields cleared, `email_verified=false`, `active=false`.
  It is *not* hard-deleted because `applicants.user_id` cascades and `jobs.owner_user_id`
  would become NULL â€” one person's request must never delete organization-wide data.
* Never touched: jobs, organizations, other users' data.

**Not implemented (gaps):** a personal-data export endpoint; a grace period / scheduled
deletion; a change-password endpoint for signed-in users (recovery uses forgot-password);
erasure of data held by third parties (email/AI providers) or in backups.

**Verification status:** the module and endpoints compile and import; they have **not been
executed** against a database (the V25.6 environment had no SQLAlchemy/Postgres). The
generic child-table deletion in `_delete_where` in particular must be run against Postgres
with foreign keys enforced before relying on it (see the checklist).

## 4. Organization lifecycle

| Event | What happens | What is preserved |
|---|---|---|
| Creation | `POST /organizations` creates the org and an ACTIVE OWNER membership atomically | â€” |
| Invitation | single-use, expiring token, bound to an email; wrong account gets 403 | invitation row |
| Role change | OWNER can grant/edit any role; ADMIN cannot grant or edit OWNER; last OWNER cannot be demoted or removed | audit rows |
| Member suspension / removal | `OrganizationMember.status` â†’ `SUSPENDED` / `REMOVED`; **V25.6:** such a user no longer resolves to the organization for recruiter data access even if a legacy owner/team row remains | the person's account, their own jobs (see below), history |
| Platform suspension | `Organization.is_active=false`, status `SUSPENDED`; published jobs â†’ `suspended` with a marker | all jobs, applicants, candidates, documents, notifications, analytics (nothing deleted). Reactivation restores exactly the jobs it suspended. |
| Deactivation ("closure") | same as suspension with status `DEACTIVATED`; there is **no hard-delete endpoint for tenant organizations** | everything above |
| Job with applicants | **V25.6:** cannot be hard-deleted (409); close it instead | applicant records |
| Job without applicants (draft/mistake) | can be deleted by the owning team | â€” |

Residual behaviours to be aware of (audit F-27, F-03): (a) a user's own id is always part of
their recruiter data scope, so jobs they created themselves stay reachable by them after they
are suspended or removed from an organization; (b) `team_owner_ids` does not check
`Organization.is_active`, so members of a platform-suspended organization keep read/write
access to their existing ATS data through recruiter endpoints (their published jobs are
unpublished). Whether that is desired is a product decision; it was not changed.

`DELETE /admin/jobs/{id}` (platform admin) and `DELETE /government/organizations/{id}` (admin,
government catalogue â€” a different entity from tenant organizations) remain hard deletes.

## 5. Where to look

* Purge policy code: `app/core/retention.py`, `scripts/retention_purge.py`.
* Erasure code: `app/core/account_lifecycle.py`, `app/api/account.py`.
* Tests (written, **not executed**): `tests/test_v25_6_security_compliance.py`
  (`test_erasure_*`, `test_sole_owner_*`, `test_retention_*`, `test_recruiter_cannot_delete_a_job_that_has_applicants`).

