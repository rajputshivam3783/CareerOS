# V23.2 — Email Notification & Template Engine

Builds a production-grade email layer — templates, a provider
abstraction, a durable queue with retry/backoff, per-category
preferences, and dev-safe testing — on top of the existing V16/V19.4
transactional-email wiring, and integrates it with V23.1's
notification event system for application-status-changed and
interview-scheduled, plus the existing OTP-based email verification
and password reset flows.

## Why this extends existing infrastructure instead of replacing it

CareerOS already had three pieces of email-adjacent infrastructure.
V23.2 extends all three rather than building parallel systems:

1. **`app.services.email_service.send_email`/`send_otp`** (V16) — the
   original SMTP wiring, used directly by auth OTP and recruiter
   offer/rejection emails. **Left completely untouched.**
   `app/email/provider.py`'s `SMTPProvider` is a new, separate
   implementation with the same settings and the same "never silently
   pretend an email was sent" production guarantee, used only by the
   new `EmailService`. `send_otp` is no longer called by
   `app/api/auth.py` (replaced by `send_transactional_email`, see
   below) but is left defined and exported — other code may still use
   it, and removing a working public function isn't a V23.2
   "stabilization" task.
2. **`EmailTemplate`/`email_templates` table** (V18.5) — a recruiter's
   own, per-company editable copy of ATS notification wording
   (application received / interview invitation / offer / rejection /
   reminder). This is a genuinely different concept from a
   *system-wide* template, so V23.2 adds a **new** table,
   `SystemEmailTemplate`/`system_email_templates`, rather than
   reusing or renaming the existing one. Both use the same
   `{{variable}}` placeholder syntax for consistency.
3. **`UserNotificationPreference`** (V19.4, extended by V23.1) —
   already had a global `email_enabled` switch and V23.1's 7 per-
   category *in-app* toggles. V23.2 adds 7 more boolean columns
   (`email_job` … `email_system`) for per-category *email* — the
   existing `GET`/`PUT /notifications/preferences` endpoint picks
   them up automatically (it already applies any field via
   `model_dump(exclude_unset=True)`), so spec section 12's suggested
   `/api/v1/notification-preferences` path is intentionally **not** a
   second endpoint — see API section below.

## Architecture

```
app/email/
    provider.py    — EmailProvider abstraction: ConsoleProvider
                      (dev-safe default) and SMTPProvider. Selected by
                      settings.email_mode via get_provider().
    templates.py    — 6 seeded SystemEmailTemplate rows + safe
                      {{variable}} rendering (HTML-escaped values,
                      required-variable validation, unknown
                      placeholders left untouched).
    preferences.py  — should_send_email(): the one preference check.
    service.py      — EmailService: queue_email / process_queue /
                      send_transactional_email. The only functions
                      that create an EmailMessage row.

app/api/notification_engine.py — PreferencesIn gains 7 new optional
                                  email_* fields (additive only);
                                  new GET /admin/email/overview
app/scheduler.py                — new careeros_email_queue job
app/api/auth.py                 — _issue() now calls
                                   send_transactional_email instead of
                                   send_otp directly
app/notifications/events.py     — application_status_changed and
                                   interview_scheduled now also queue
                                   an email (application_created and
                                   interview_updated remain in-app-
                                   only — see "At-minimum scope" below)
```

## Provider abstraction

```python
class EmailProvider:
    def send(self, message: OutgoingEmail) -> None: ...

class ConsoleProvider(EmailProvider):   # settings.email_mode == "console" (default)
class SMTPProvider(EmailProvider):      # settings.email_mode == "smtp"

def get_provider() -> EmailProvider: ...
```

`EmailService` never imports `smtplib` or knows what "SMTP" means —
it calls `get_provider().send(message)`. `EMAIL_MODE=console` (the
default, and what every test in this suite runs under) renders and
logs every email, never opens a socket — this is the dev-safe testing
mechanism spec section 13 asks for. `EMAIL_MODE=smtp` in production
with `SMTP_HOST`/`SMTP_FROM_EMAIL` unset raises immediately at send
time rather than silently no-op'ing, the same guarantee
`send_email`/`send_otp` already gave V16's OTP flow.

## Templates

Six seeded templates (`app.email.templates.SEED_TEMPLATES`),
lazy-created into `SystemEmailTemplate` on first use (same pattern
`app.api.email_templates._get_or_seed` already established for
recruiter templates):

| Key | Required variables |
|---|---|
| `WELCOME_EMAIL` | `user_name`, `action_url` |
| `EMAIL_VERIFICATION` | `user_name`, `otp_code` |
| `PASSWORD_RESET` | `user_name`, `otp_code` |
| `APPLICATION_STATUS_CHANGED` | `user_name`, `job_title`, `company_name`, `application_status`, `action_url` |
| `INTERVIEW_SCHEDULED` | `user_name`, `job_title`, `company_name`, `interview_date`, `interview_type`, `action_url` |
| `SYSTEM_NOTIFICATION` | `user_name`, `notification_title`, `notification_message`, `action_url` |

Rendering (`app.email.templates.render`) HTML-escapes every
substituted **value** before inserting it into the HTML body (never
the surrounding template markup) — this is the HTML/template-
injection defense spec section 16 asks for. A missing required
variable raises `TemplateError` rather than rendering a broken email
with a literal `{{missing_var}}` in it. Plain-text bodies are never
escaped (there's no markup to break out of). This is intentionally
plain substitution, not a real templating language — no
loops/conditionals/attribute access, so a template can never reach
into an arbitrary backend object (spec section 6).

`WELCOME_EMAIL` is seeded and ready to use but not wired to a call
site this version (not in spec section 10's "at minimum" list).

## Queue, retry, and failure isolation

**`queue_email()`** — fire-and-forget: checks the recipient's
preference for the given category, validates the template, inserts a
`QUEUED` `EmailMessage`, and returns immediately. **No SMTP call
happens inside this function at all** — spec section 20 explicitly
asks to avoid synchronous sends in critical request paths, and this
is called directly from `app.notifications.events`, which itself is
called from inside `app.applications.service`'s
create_application/change_status request handlers. Every failure mode
(bad template, preference says no, a DB error) is a safe `None`
return, never an exception reaching the caller.

**`process_queue()`** — called by the new `careeros_email_queue`
scheduler job (every `EMAIL_QUEUE_INTERVAL_MINUTES`, default 2)
exactly like V7's notification scan and V19.4's automation scan
already are. Picks up every `QUEUED`/`RETRYING` row whose
`scheduled_at` has arrived (bounded by `limit`, default 50) and
attempts delivery. A send failure records an `EmailDeliveryAttempt`,
increments `attempts`, and either schedules a retry
(`scheduled_at = now + email_retry_backoff_seconds * 2^(attempts-1)`
— exponential backoff, so attempt 1 retries after the base interval,
attempt 2 after 2×, etc.) or, once `attempts >= max_attempts`
(default 4), marks the row `FAILED` permanently — no infinite retry
loop, matching spec section 8.

**`send_transactional_email()`** — synchronous, used only for
email verification and password reset, where the user is actively
waiting on the same page for a code. Never checks preferences (see
Preferences section). Never raises — a transport failure is recorded
(`FAILED`, with `last_error`) and logged, but always returns `False`
rather than propagating, so a failed OTP email can never turn a
successful registration or password-reset request into a 500. The
row is persisted (`PROCESSING`) *before* rendering is attempted, so
even a bad-template failure leaves a trackable row rather than
vanishing silently.

Both queue paths are exercised by dedicated tests that monkeypatch the
provider to always fail and assert the expected `RETRYING` →
`FAILED` progression, and that a provider failure during registration
still returns a successful HTTP response.

## Preferences

`app.email.preferences.should_send_email(db, user_id, category)` is
the single choke point: returns `False` only if the user has
`email_enabled=False` globally, or the specific category's `email_*`
column is `False`. A user with no preference row yet (never visited
the preferences page) always gets `True` — same "unchanged default
behavior" guarantee every flag on `UserNotificationPreference`
already gives.

**Security-critical emails (verification, password reset) never call
this function at all** — `send_transactional_email` has no preference
check anywhere in it, by construction. This is spec section 11's
explicit requirement: these "must not be disabled through ordinary
notification preferences."

## API

```
GET/PUT /api/v1/notifications/preferences   — EXISTING (V19.4)
    endpoint, PATCHable body now also accepts email_job, email_
    application, email_interview, email_deadline, email_recruiter,
    email_ai, email_system (alongside V23.1's notify_* fields).
    Spec section 12 suggests GET/PATCH /api/v1/notification-
    preferences as a new path — deliberately NOT added as a second,
    near-identical endpoint; this project's own guardrail against
    duplicate systems applies as much to near-duplicate API paths as
    to duplicate tables.

GET  /api/v1/admin/email/overview           — NEW, admin-only
    (reuses the existing `guard` dependency from app.api.admin).
    Status counts + the 20 most recent failures — deliberately
    minimal per spec section 19 ("do not build a huge analytics
    system yet").
```

No new public-facing "send an email" endpoint exists anywhere —
emails are only ever produced by server-side event triggers or the
auth OTP flow, never by an arbitrary API call, which is itself a
security property (spec section 16: "never accept arbitrary email
headers/content from frontend input").

## Notification → email integration

Only `application_status_changed` and `interview_scheduled` queue an
email this version — matching spec section 10's literal "at minimum"
list and the two templates that have dedicated content for them.
`application_created` and `interview_updated` remain in-app-only,
same as V23.1. Adding email to a currently-unwired event needs no new
plumbing: `app.notifications.events._safe_notify` already accepts an
`email_template_key`/`email_variables` pair generically — see that
file's own "Extensibility note."

## Security

- **Recipient validation**: the recipient is always the authenticated
  user's own `User.email` on file (looked up server-side by
  `user_id`), never a client-supplied address.
- **Header injection**: `EmailMessage`/`smtplib.EmailMessage` set
  `Subject`/`From`/`To` from server-controlled strings (a rendered
  template subject, `settings.smtp_from_email`, and the looked-up
  recipient) — never raw, unvalidated user input assigned directly
  into a header field.
- **Template/HTML injection**: see Templates section — every
  substituted value is HTML-escaped before insertion into the HTML
  body; there is no expression language for a value to escape into.
- **Unsafe URLs**: every `action_url` used in a template is a
  same-origin internal path (e.g. `/applications/{id}`), built the
  same way V23.1's notification `action_url`s already are — never an
  arbitrary external URL.
- **Secret leakage**: the OTP code is passed to `render()` only as an
  in-memory `render_variables` argument; `persisted_variables`
  (what actually reaches `EmailMessage.variables_json`) never includes
  it — see `_issue()` in `app/api/auth.py` and
  `send_transactional_email`'s own docstring. Verified by a dedicated
  test asserting the persisted JSON never contains the 6-digit code.
- **Log leakage**: `logger.error(...)` calls throughout `app/email/`
  log a short, safe summary (template key, user id, exception class/
  message truncated to 500 chars) — never a full raw exception that
  might embed SMTP credentials, and never a rendered email body or
  the OTP code itself.

## Development mode

`EMAIL_MODE=console` (the default, and what this repo's test suite
runs under) renders every email and logs it via
`logger.info(...)` — the subject, text body, and HTML body are all
visible in server logs for local debugging, but no network connection
is ever opened. Switching to `EMAIL_MODE=smtp` is the only way to
actually deliver anything; `docker-compose.production.yml` sets
`EMAIL_MODE: ${EMAIL_MODE:-smtp}` so production defaults to actually
sending rather than silently defaulting to console mode.

## Testing

`backend/tests/test_v23_2_email_system.py` — runs entirely under
`EMAIL_MODE=console`, so **no real SMTP connection is ever opened**;
provider failures are simulated by monkeypatching
`app.email.service.get_provider` (the name as it's actually called
from within `service.py` — `service.py` did `from app.email.provider
import get_provider`, a name-bound import, so patching
`app.email.provider.get_provider` directly would not have affected
`service.py`'s already-bound reference; this was caught and fixed
during this version's own development, the same "from X import Y
requires patching the importing module" lesson V22.4's tests already
established for `completion_service.route_complete`).

Covers: template rendering + required-variable validation + HTML
escaping; unknown template key rejection; queue → console-send → SENT
happy path; preference enforcement (a disabled category never creates
a row); retry-then-permanent-failure (RETRYING with backoff, then
FAILED after max_attempts); idempotency (duplicate dedupe_key returns
the existing row, no second insert); application-status-change and
interview-scheduled each queuing exactly one email with the right
template/variables; registration queuing a verification email whose
persisted variables never contain the OTP code; a provider failure
during registration still returning a successful HTTP response; the
existing preferences endpoint accepting the new `email_*` fields; and
the new admin overview endpoint requiring admin auth.

**Execution status: NOT VERIFIED.** Same sandbox constraint as every
prior V22.x/V23.x release — no network egress (`pip install`/`npm
install` both 403, reconfirmed this session), so `pytest` could not
actually run. Every new/changed Python file passed `python -m
py_compile`; an AST-based unused-import scan found nothing; a scripted
model-to-migration column diff confirmed exact parity for all three
new tables and the 7 new preference columns; the migration file was
run through the project's own statement-splitting logic (18
statements, all parse correctly). Please run `pytest
backend/tests/test_v23_2_email_system.py` and the full existing
suite, plus `npm run build`, in an environment with registry access
before deploying.

## Known limitations

- `WELCOME_EMAIL` is seeded but not wired to any call site (spec
  didn't require it in the "at minimum" list).
- `application_created` and `interview_updated` remain in-app-only —
  deliberately, per spec's literal minimum-integration list.
- `send_otp`/`send_email` in `app.services.email_service` are no
  longer called from `app/api/auth.py` but are left defined
  (still used by `app/services/notification_channels.py` and
  `app/api/recruiter.py`) — not dead code, just no longer this
  version's path for OTP delivery.
- If `get_provider()` itself raises (production misconfiguration —
  `EMAIL_MODE=smtp` with no SMTP host configured), that exception
  propagates out of `process_queue()` for that scheduler tick rather
  than being caught per-message — consistent with this codebase's
  existing "fail loudly on production misconfiguration" philosophy
  (the same guarantee `send_email` already gives), but worth knowing:
  a misconfigured production deployment will see the whole
  `careeros_email_queue` job fail (and retry, per `app.scheduler`'s
  `_with_retry`) rather than each individual email being marked
  `FAILED` one at a time.
