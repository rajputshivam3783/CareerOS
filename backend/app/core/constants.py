"""Shared classification vocabularies (V1 Government + V3 Private/
Internship/Apprenticeship). Kept as plain lists rather than a DB enum
so adding a new value later doesn't need a schema migration — the
column is a plain VARCHAR and these lists are only used for
documentation/validation hints in the API layer.
"""

JOB_TYPES = ["Government", "Private", "Internship", "Apprenticeship"]

EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Contract", "Internship", "Apprenticeship", "Freelance"]

WORK_MODES = ["Onsite", "Remote", "Hybrid"]

# V18.1 — Company module (app.api.company). Plain lists for the same
# reason as JOB_TYPES/EMPLOYMENT_TYPES/WORK_MODES above: validation
# hints only, backed by a plain VARCHAR column.
COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5000+"]
COMPANY_VERIFICATION_STATUSES = ["unverified", "pending", "verified", "rejected"]

# V18.2 — recruiter ATS job management. `JOB_LIFECYCLE_STATUSES` extends
# the pre-existing jobs.status vocabulary ("review"/"published"/
# "rejected", owned by app.api.admin's approval workflow — left
# untouched) with two recruiter-only states: a job now starts as
# "draft" instead of going straight into the public review queue, and
# a previously-published job can be "closed" or "archived" without
# being deleted.
EMAIL_TEMPLATE_TYPES = [
    "application_received",
    "interview_invitation",
    "interview_reminder",
    "offer",
    "rejection",
]

# V18.5 — recruiter email templates (app.api.email_templates). One
# editable row per (organization, template_type); a recruiter who
# hasn't customized a type yet sees these seed values rather than a
# blank editor. Placeholders use {{variable}} syntax and are replaced
# by app.api.email_templates.render_template — this module only
# stores/renders text, it does not send anything (Notifications is
# untouched, per V18 scope).
EMAIL_TEMPLATE_DEFAULTS: dict[str, dict[str, str]] = {
    "application_received": {
        "label": "Application received",
        "subject": "We've received your application for {{job_title}}",
        "body": (
            "Hi {{candidate_name}},\n\n"
            "Thanks for applying to {{job_title}} at {{company_name}}. "
            "Our team is reviewing applications and will follow up if there's a match.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
    "interview_invitation": {
        "label": "Interview invitation",
        "subject": "Interview invitation — {{job_title}} at {{company_name}}",
        "body": (
            "Hi {{candidate_name}},\n\n"
            "We'd like to invite you to interview for {{job_title}}.\n\n"
            "Type: {{interview_type}}\nDate: {{interview_date}}\nTime: {{interview_time}}\n"
            "Meeting link: {{meeting_link}}\n\n"
            "Please confirm your availability.\n\nBest,\n{{recruiter_name}}"
        ),
    },
    "interview_reminder": {
        "label": "Interview reminder",
        "subject": "Reminder: your interview for {{job_title}} is coming up",
        "body": (
            "Hi {{candidate_name}},\n\n"
            "This is a reminder of your upcoming interview for {{job_title}} "
            "on {{interview_date}} at {{interview_time}}.\n\n"
            "Meeting link: {{meeting_link}}\n\nBest,\n{{recruiter_name}}"
        ),
    },
    "offer": {
        "label": "Offer",
        "subject": "Offer from {{company_name}} — {{job_title}}",
        "body": (
            "Hi {{candidate_name}},\n\n"
            "We're delighted to offer you the {{job_title}} position at {{company_name}}.\n\n"
            "Please find the offer details attached and let us know if you have any questions.\n\n"
            "Congratulations,\n{{recruiter_name}}"
        ),
    },
    "rejection": {
        "label": "Rejection",
        "subject": "Update on your application for {{job_title}}",
        "body": (
            "Hi {{candidate_name}},\n\n"
            "Thank you for taking the time to apply for {{job_title}} at {{company_name}} "
            "and for interviewing with our team. "
            "We've decided to move forward with another candidate for this role.\n\n"
            "We appreciate your interest and encourage you to apply for future openings.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
}

EMAIL_TEMPLATE_VARIABLES = [
    "candidate_name", "job_title", "company_name", "recruiter_name",
    "interview_type", "interview_date", "interview_time", "meeting_link",
]

JOB_LIFECYCLE_STATUSES = ["draft", "review", "published", "closed", "archived", "rejected"]

# V24.3 — Kanban pipeline stages shown on the recruiter Candidate
# Pipeline / Hiring Workflow board — richer than (and independent of)
# `Applicant.status`. This is the recruiter-side hiring status; it is
# never used to overwrite the candidate-facing `Applicant.status` (see
# docs/V24_3_CANDIDATE_PIPELINE.md, "Status separation").
#
# Renamed in V24.3 from the V18.2 vocabulary (applied/shortlisted/
# screening/interview/technical_round/hr_round/offer/accepted) to the
# canonical hiring-workflow names below, so the stored value matches
# what recruiters see on the board and what the API documents. A data
# migration (migrations/v24_3_candidate_pipeline.sql) rewrites existing
# rows using LEGACY_PIPELINE_STAGE_MAP below; no other column or table
# changes meaning. `technical_round` and `hr_round` both collapse into
# a single `assessment` stage — V24.3 doesn't need to distinguish them
# on the board, and a recruiter can still tell rounds apart via the
# existing `Interview.round_name` on each scheduled interview.
PIPELINE_STAGES = [
    "new", "reviewing", "shortlisted", "assessment", "interview",
    "offer", "hired", "rejected", "withdrawn",
]

# Forward order of the "active" hiring stages (excludes the two
# terminal off-ramps). Used to compute time-in-stage, conversion
# metrics, and whether a given stage change is a "forward" or
# "backward" move (recorded on RecruiterPipelineHistory for reporting
# only — backward moves are never blocked, see STAGE_TRANSITIONS_NOTE
# below).
PIPELINE_FORWARD_STAGES = ["new", "reviewing", "shortlisted", "assessment", "interview", "offer", "hired"]

# Stages a candidate's pipeline row does not move on from once here.
PIPELINE_TERMINAL_STAGES = ("rejected", "withdrawn")

# V24.3 stage-transition policy (spec section 6): "Do not make the
# workflow unnecessarily restrictive." Any active/hired stage may move
# to REJECTED or WITHDRAWN at any time; any two stages in
# PIPELINE_FORWARD_STAGES may be moved between in either direction
# (e.g. INTERVIEW -> REVIEWING is a valid backward correction); a
# candidate in REJECTED/WITHDRAWN may be reactivated back into any
# forward stage. The only transition rejected outright is moving a
# stage to itself (a no-op that would just spam pipeline history). See
# app.recruiter_pipeline.service.validate_transition.
STAGE_TRANSITIONS_NOTE = (
    "Any stage may move to REJECTED/WITHDRAWN; any two forward stages "
    "may be moved between in either direction; REJECTED/WITHDRAWN may "
    "be reactivated into any forward stage; same-stage moves are rejected."
)

# V18.2 -> V24.3 rename map, used once by the data migration and kept
# here (rather than only in the .sql file) so tests / one-off scripts
# can apply the same mapping without re-deriving it.
LEGACY_PIPELINE_STAGE_MAP = {
    "applied": "new",
    "screening": "reviewing",
    "shortlisted": "shortlisted",
    "technical_round": "assessment",
    "hr_round": "assessment",
    "interview": "interview",
    "offer": "offer",
    "accepted": "hired",
    "rejected": "rejected",
    "withdrawn": "withdrawn",
}

# V14 introduced government recruitment lifecycle events (RecruitmentUpdate.
# update_type); V16 adds the post-exam stages a real recruitment also goes
# through (cutoff/merit list/document verification/counselling/joining),
# closing the gap with the "Notification -> Apply -> Exam -> Admit Card ->
# Answer Key -> Result -> DV -> Joining" lifecycle. Centralized here so
# app.api.admin (write-side validation) and app.api.platform (read-side
# section routing) can't drift out of sync with each other.
RECRUITMENT_UPDATE_TYPES = {
    "result", "admit_card", "answer_key", "admission", "syllabus", "exam_date", "notice",
    "cutoff", "merit_list", "dv", "counselling", "joining",
    # V19.1 — Government Recruitment Core. Fills out the remaining
    "notification", "application_open", "application_closed", "correction_window",
    "city_intimation", "objection_window", "final_answer_key", "score_card",
    "medical", "final_selection", "completed", "cancelled",
}

# V19.1 — GovernmentOrganization.govt_level and Job.govt_level share this vocabulary.
GOVERNMENT_LEVELS = ["Central", "State", "PSU", "University", "Board", "Commission"]

# V19.1 — GovernmentOrganization.status.
ORGANIZATION_STATUSES = ["active", "inactive"]

# SourceRegistry.collector_type. Mirrors the adapter families
# supported by app.ingestion.adapters.configured.ConfiguredSourceAdapter:
#   official_html  -> SmartOfficialAdapter (link-scanning notice board)
#   html_list      -> HTMLListAdapter (CSS-selector table/list)
#   rss            -> RSSAdapter (RSS 2.0 / Atom)
#   xml            -> XMLFeedAdapter (arbitrary XML with a configurable item path)
#   json_api       -> JSONAPIAdapter (JSON REST/feed endpoint)
#   pdf_metadata   -> PDFMetadataAdapter (listing page whose links are PDFs;
#                     title/date come from link text and, best-effort, the PDF itself)
#   sitemap        -> SitemapAdapter (sitemap.xml filtered by a URL pattern)
# "selenium"/"playwright" are V19.2 registry-only placeholders for
# Future Browser Automation — no such collector is implemented yet,
# per this version's scope (see ROADMAP.md V19.3+).
SOURCE_COLLECTOR_TYPES = [
    "official_html", "html_list", "rss", "xml", "json_api",
    "pdf_metadata", "sitemap", "selenium", "playwright",
]

# V19.1 — SourceRegistry.status.
SOURCE_REGISTRY_STATUSES = ["active", "paused", "disabled"]
