"""V23.2 — System email templates.

Same ``{{variable}}`` placeholder convention app.api.email_templates
already established for recruiter templates (kept consistent on
purpose), with one addition needed for *system* emails: values
substituted into the HTML body are HTML-escaped before insertion —
recruiter templates render from a recruiter's own trusted-ish company
data reviewed by that recruiter; system templates render candidate-
and-company data that could, transitively, contain another user's
free-text input (a job title scraped from an external source, a
company name) and must not be able to break out of the surrounding
HTML (spec security section: "template injection" / "HTML injection").
Plain-text bodies are never escaped (nothing to break out of).

This is intentionally simple substitution, not a real templating
engine (no loops/conditionals/arbitrary attribute access) — spec:
"Never allow templates to access arbitrary backend objects."
"""

from __future__ import annotations

import html
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import SystemEmailTemplate

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

_LAYOUT_HTML = """<!DOCTYPE html>
<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f8fafc;margin:0;padding:24px">
<table role="presentation" width="100%%" style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden">
<tr><td style="background:#1e3a8a;padding:20px 28px"><span style="color:#ffffff;font-size:18px;font-weight:700">CareerOS</span></td></tr>
<tr><td style="padding:28px">%s</td></tr>
<tr><td style="padding:16px 28px;color:#94a3b8;font-size:12px;border-top:1px solid #e2e8f0">You're receiving this because of activity on your CareerOS account. Manage your notification preferences in Settings.</td></tr>
</table></body></html>"""

# key -> (subject, html_inner_body, text_body, [required variable names])
SEED_TEMPLATES: dict[str, dict] = {
    "WELCOME_EMAIL": {
        "subject": "Welcome to CareerOS, {{user_name}}!",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Welcome, {{user_name}}!</h2>"
            "<p>Your CareerOS account is ready. Track applications, get AI-assisted interview prep, and more — all in one place.</p>"
            "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:12px'>Get started</a></p>"
        ),
        "text_body": "Welcome, {{user_name}}!\n\nYour CareerOS account is ready. Track applications, get AI-assisted interview prep, and more — all in one place.\n\nGet started: {{action_url}}",
        "variables": ["user_name", "action_url"],
    },
    "EMAIL_VERIFICATION": {
        "subject": "Verify your CareerOS email",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Verify your email</h2>"
            "<p>Hi {{user_name}}, use this code to verify your CareerOS account:</p>"
            "<p style='font-size:28px;font-weight:800;letter-spacing:4px;text-align:center;margin:20px 0'>{{otp_code}}</p>"
            "<p>This code expires shortly. If you didn't request this, you can safely ignore this email.</p>"
        ),
        "text_body": "Hi {{user_name}},\n\nUse this code to verify your CareerOS account: {{otp_code}}\n\nThis code expires shortly. If you didn't request this, you can safely ignore this email.",
        "variables": ["user_name", "otp_code"],
    },
    "PASSWORD_RESET": {
        "subject": "Reset your CareerOS password",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Reset your password</h2>"
            "<p>Hi {{user_name}}, use this code to reset your CareerOS password:</p>"
            "<p style='font-size:28px;font-weight:800;letter-spacing:4px;text-align:center;margin:20px 0'>{{otp_code}}</p>"
            "<p>This code expires shortly. If you didn't request this, you can safely ignore this email — your password will not be changed.</p>"
        ),
        "text_body": "Hi {{user_name}},\n\nUse this code to reset your CareerOS password: {{otp_code}}\n\nThis code expires shortly. If you didn't request this, you can safely ignore this email — your password will not be changed.",
        "variables": ["user_name", "otp_code"],
    },
    "APPLICATION_STATUS_CHANGED": {
        "subject": "{{company_name}}: your application is now {{application_status}}",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Application update</h2>"
            "<p>Hi {{user_name}}, your application for <b>{{job_title}}</b> at <b>{{company_name}}</b> is now <b>{{application_status}}</b>.</p>"
            "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:12px'>View application</a></p>"
        ),
        "text_body": "Hi {{user_name}},\n\nYour application for {{job_title}} at {{company_name}} is now {{application_status}}.\n\nView it here: {{action_url}}",
        "variables": ["user_name", "job_title", "company_name", "application_status", "action_url"],
    },
    "INTERVIEW_SCHEDULED": {
        "subject": "Interview scheduled: {{company_name}}",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Interview scheduled</h2>"
            "<p>Hi {{user_name}}, your {{interview_type}} interview for <b>{{job_title}}</b> at <b>{{company_name}}</b> is scheduled for <b>{{interview_date}}</b>.</p>"
            "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:12px'>View details</a></p>"
        ),
        "text_body": "Hi {{user_name}},\n\nYour {{interview_type}} interview for {{job_title}} at {{company_name}} is scheduled for {{interview_date}}.\n\nView details: {{action_url}}",
        "variables": ["user_name", "job_title", "company_name", "interview_date", "interview_type", "action_url"],
    },
    "SYSTEM_NOTIFICATION": {
        "subject": "{{notification_title}}",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>{{notification_title}}</h2>"
            "<p>Hi {{user_name}}, {{notification_message}}</p>"
            "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:12px'>View in CareerOS</a></p>"
        ),
        "text_body": "Hi {{user_name}},\n\n{{notification_message}}\n\nView in CareerOS: {{action_url}}",
        "variables": ["user_name", "notification_title", "notification_message", "action_url"],
    },
    # V23.3 — Smart Job Alerts. INSTANT covers exactly one job. DAILY/
    # WEEKLY are digests — spec: "Do not send one email per job for
    # digest alerts" — but this template engine deliberately does no
    # looping/raw-HTML injection (every substituted value is HTML-
    # escaped, on purpose — see this module's docstring on template/
    # HTML injection), so a digest can't embed an arbitrary-length,
    # pre-rendered job list as a single variable without either
    # bypassing that escaping (a real injection risk, since job
    # titles/company names ultimately come from scraped/recruiter-
    # submitted data) or adding loop syntax this engine intentionally
    # doesn't have. Instead the digest uses a fixed block of up to
    # DIGEST_TOP_N (see app.job_alerts.execution) numbered per-job
    # placeholders, each independently escaped like any other
    # variable, plus a plain "and N more" count for the rest — same
    # "top relevant jobs" scope the spec asks for, with zero new
    # injection surface.
    "JOB_ALERT_INSTANT": {
        "subject": "New match for \"{{alert_name}}\": {{job_title}}",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>New job match</h2>"
            "<p>Hi {{user_name}}, a new job matches your alert <b>\"{{alert_name}}\"</b>:</p>"
            "<p style='margin:16px 0;padding:14px;background:#f1f5f9;border-radius:8px'>"
            "<b>{{job_title}}</b><br>{{company_name}} &middot; {{job_location}}<br>"
            "<span style='color:#64748b;font-size:13px'>{{match_reason}}</span></p>"
            "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:4px'>View job</a></p>"
        ),
        "text_body": "Hi {{user_name}},\n\nA new job matches your alert \"{{alert_name}}\":\n\n{{job_title}} at {{company_name}} ({{job_location}})\n{{match_reason}}\n\nView it here: {{action_url}}",
        "variables": ["user_name", "alert_name", "job_title", "company_name", "job_location", "match_reason", "action_url"],
    },
    "JOB_ALERT_DAILY": {
        "subject": "{{match_count}} new job(s) today for \"{{alert_name}}\"",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Your daily job alert</h2>"
            "<p>Hi {{user_name}}, {{match_count}} new job(s) matched <b>\"{{alert_name}}\"</b> today:</p>"
            + "".join(
                f"<p style='margin:10px 0;padding:12px;background:#f1f5f9;border-radius:8px'>"
                f"<b>{{{{job_{i}_title}}}}</b><br>{{{{job_{i}_company}}}} &middot; {{{{job_{i}_location}}}}<br>"
                f"<span style='color:#64748b;font-size:13px'>{{{{job_{i}_reason}}}}</span></p>"
                for i in range(1, 6)
            )
            + "<p style='color:#64748b;font-size:13px'>{{more_count_text}}</p>"
            + "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:4px'>View all matches</a></p>"
        ),
        "text_body": "Hi {{user_name}},\n\n{{match_count}} new job(s) matched \"{{alert_name}}\" today:\n\n"
        + "\n".join(f"- {{{{job_{i}_title}}}} at {{{{job_{i}_company}}}} ({{{{job_{i}_location}}}})" for i in range(1, 6))
        + "\n{{more_count_text}}\n\nView all matches: {{action_url}}",
        "variables": (
            ["user_name", "alert_name", "match_count", "more_count_text", "action_url"]
            + [f"job_{i}_{field}" for i in range(1, 6) for field in ("title", "company", "location", "reason")]
        ),
    },
    "JOB_ALERT_WEEKLY": {
        "subject": "{{match_count}} new job(s) this week for \"{{alert_name}}\"",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Your weekly job alert</h2>"
            "<p>Hi {{user_name}}, {{match_count}} new job(s) matched <b>\"{{alert_name}}\"</b> this week:</p>"
            + "".join(
                f"<p style='margin:10px 0;padding:12px;background:#f1f5f9;border-radius:8px'>"
                f"<b>{{{{job_{i}_title}}}}</b><br>{{{{job_{i}_company}}}} &middot; {{{{job_{i}_location}}}}<br>"
                f"<span style='color:#64748b;font-size:13px'>{{{{job_{i}_reason}}}}</span></p>"
                for i in range(1, 6)
            )
            + "<p style='color:#64748b;font-size:13px'>{{more_count_text}}</p>"
            + "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:4px'>View all matches</a></p>"
        ),
        "text_body": "Hi {{user_name}},\n\n{{match_count}} new job(s) matched \"{{alert_name}}\" this week:\n\n"
        + "\n".join(f"- {{{{job_{i}_title}}}} at {{{{job_{i}_company}}}} ({{{{job_{i}_location}}}})" for i in range(1, 6))
        + "\n{{more_count_text}}\n\nView all matches: {{action_url}}",
        "variables": (
            ["user_name", "alert_name", "match_count", "more_count_text", "action_url"]
            + [f"job_{i}_{field}" for i in range(1, 6) for field in ("title", "company", "location", "reason")]
        ),
    },
    # V23.4 — Communication Center reminders. See
    # app.communication.reminders for what fires each of these.
    "INTERVIEW_REMINDER": {
        "subject": "Reminder: {{interview_type}} interview {{time_phrase}}",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Interview reminder</h2>"
            "<p>Hi {{user_name}}, your {{interview_type}} interview for <b>{{job_title}}</b> at "
            "<b>{{company_name}}</b> is {{time_phrase}} ({{interview_date}}).</p>"
            "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;"
            "padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:12px'>View details</a></p>"
        ),
        "text_body": "Hi {{user_name}},\n\nYour {{interview_type}} interview for {{job_title}} at {{company_name}} "
        "is {{time_phrase}} ({{interview_date}}).\n\nView details: {{action_url}}",
        "variables": ["user_name", "interview_type", "job_title", "company_name", "interview_date", "time_phrase", "action_url"],
    },
    "DEADLINE_REMINDER": {
        "subject": "{{time_phrase}}: {{job_title}} application deadline",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Deadline reminder</h2>"
            "<p>Hi {{user_name}}, the application deadline for <b>{{job_title}}</b> at "
            "<b>{{company_name}}</b> is {{time_phrase}} ({{deadline_date}}).</p>"
            "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;"
            "padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:12px'>View application</a></p>"
        ),
        "text_body": "Hi {{user_name}},\n\nThe application deadline for {{job_title}} at {{company_name}} "
        "is {{time_phrase}} ({{deadline_date}}).\n\nView it here: {{action_url}}",
        "variables": ["user_name", "job_title", "company_name", "deadline_date", "time_phrase", "action_url"],
    },
    "TASK_DUE_REMINDER": {
        "subject": "{{time_phrase}}: {{task_title}}",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Task reminder</h2>"
            "<p>Hi {{user_name}}, your task <b>\"{{task_title}}\"</b> on the application for "
            "<b>{{job_title}}</b> is {{time_phrase}} ({{due_date}}).</p>"
            "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;"
            "padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:12px'>View task</a></p>"
        ),
        "text_body": "Hi {{user_name}},\n\nYour task \"{{task_title}}\" on the application for {{job_title}} "
        "is {{time_phrase}} ({{due_date}}).\n\nView it here: {{action_url}}",
        "variables": ["user_name", "task_title", "job_title", "due_date", "time_phrase", "action_url"],
    },
    # Same fixed-slot-plus-"and N more" pattern as JOB_ALERT_DAILY/WEEKLY
    # above, for the same reason (this template engine deliberately has
    # no loop syntax — see the JOB_ALERT_DAILY comment). Each numbered
    # slot is a generic (label, title, detail) triple so the digest can
    # mix interview/deadline/task/application/job items in one list.
    "DAILY_CAREER_DIGEST": {
        "subject": "Your CareerOS digest: {{item_count}} item(s) need attention",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>Your daily digest</h2>"
            "<p>Hi {{user_name}}, here's what needs your attention today:</p>"
            + "".join(
                f"<p style='margin:10px 0;padding:12px;background:#f1f5f9;border-radius:8px'>"
                f"<span style='color:#1e3a8a;font-size:12px;font-weight:700;text-transform:uppercase'>"
                f"{{{{item_{i}_label}}}}</span><br><b>{{{{item_{i}_title}}}}</b><br>"
                f"<span style='color:#64748b;font-size:13px'>{{{{item_{i}_detail}}}}</span></p>"
                for i in range(1, 6)
            )
            + "<p style='color:#64748b;font-size:13px'>{{more_count_text}}</p>"
            + "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;"
            "padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:4px'>Open Communication Center</a></p>"
        ),
        "text_body": "Hi {{user_name}},\n\nHere's what needs your attention today:\n\n"
        + "\n".join(f"- [{{{{item_{i}_label}}}}] {{{{item_{i}_title}}}} — {{{{item_{i}_detail}}}}" for i in range(1, 6))
        + "\n{{more_count_text}}\n\nOpen Communication Center: {{action_url}}",
        "variables": (
            ["user_name", "item_count", "more_count_text", "action_url"]
            + [f"item_{i}_{field}" for i in range(1, 6) for field in ("label", "title", "detail")]
        ),
    },
    # V25.1 — Multi-Tenant Architecture & Organization Management.
    # Sent from app.api.organizations.invite_member via the existing
    # queue_email() path (spec section 15/16: reuse V23 email
    # infrastructure, do not build a parallel system). `action_url`
    # carries the raw invitation token in the query string — the
    # token itself is never persisted anywhere except as a one-way
    # hash (OrganizationInvitation.token_hash) and is never logged.
    "ORGANIZATION_INVITATION": {
        "subject": "You've been invited to join {{organization_name}} on CareerOS",
        "html_body": _LAYOUT_HTML % (
            "<h2 style='margin:0 0 12px'>You're invited to {{organization_name}}</h2>"
            "<p>Hi {{user_name}}, {{inviter_name}} has invited you to join "
            "<strong>{{organization_name}}</strong> on CareerOS as a {{role}}.</p>"
            "<p><a href='{{action_url}}' style='display:inline-block;background:#1e3a8a;color:#fff;"
            "padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:12px'>"
            "Accept invitation</a></p>"
            "<p>This invitation expires in {{expires_in}}. If you weren't expecting this, "
            "you can safely ignore this email.</p>"
        ),
        "text_body": "Hi {{user_name}},\n\n{{inviter_name}} has invited you to join {{organization_name}} "
        "on CareerOS as a {{role}}.\n\nAccept: {{action_url}}\n\n"
        "This invitation expires in {{expires_in}}. If you weren't expecting this, you can safely ignore this email.",
        "variables": ["user_name", "inviter_name", "organization_name", "role", "action_url", "expires_in"],
    },
}

# V23.3 — how many jobs the DAILY/WEEKLY digest templates show
# individually before falling back to "and N more" — see the
# JOB_ALERT_DAILY/WEEKLY comment above for why this is a fixed slot
# count rather than a rendered loop.
DIGEST_TOP_N = 5

TEMPLATE_KEYS: tuple[str, ...] = tuple(SEED_TEMPLATES.keys())


class TemplateError(Exception):
    pass


def _substitute(text: str, values: dict[str, str], *, escape: bool) -> str:
    def _sub(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)  # leave unknown placeholders untouched, never blank them
        value = str(values[key])
        return html.escape(value) if escape else value

    return _PLACEHOLDER.sub(_sub, text)


def get_or_seed_template(db: Session, template_key: str) -> SystemEmailTemplate:
    if template_key not in SEED_TEMPLATES:
        raise TemplateError(f"Unknown template_key {template_key!r}. Must be one of {TEMPLATE_KEYS}")
    row = db.scalar(select(SystemEmailTemplate).where(SystemEmailTemplate.template_key == template_key))
    if row:
        return row
    seed = SEED_TEMPLATES[template_key]
    row = SystemEmailTemplate(
        template_key=template_key,
        subject=seed["subject"],
        html_body=seed["html_body"],
        text_body=seed["text_body"],
        variables_json=json.dumps(seed["variables"]),
        active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def validate_variables(template: SystemEmailTemplate, values: dict[str, str]) -> None:
    required = json.loads(template.variables_json)
    missing = [v for v in required if v not in values]
    if missing:
        raise TemplateError(f"Missing required variable(s) for {template.template_key}: {missing}")


def render(template: SystemEmailTemplate, values: dict[str, str]) -> tuple[str, str, str]:
    """Returns (subject, html_body, text_body). Raises TemplateError if
    a required variable is missing — callers must supply everything
    the template needs; there is no silent partial-render for a real
    send (app.api.email_templates.preview_template's "leave it
    untouched" behavior is for the recruiter's *editor preview* only,
    not for an actual outgoing email)."""
    validate_variables(template, values)
    subject = _substitute(template.subject, values, escape=False)
    html_body = _substitute(template.html_body, values, escape=True)
    text_body = _substitute(template.text_body, values, escape=False)
    return subject, html_body, text_body
