"""V24.3 — Candidate Pipeline & Hiring Workflow.

Builds on the V9/V16/V18.2 recruiter ATS (``Applicant``,
``Applicant.pipeline_stage``, ``ApplicantNote``, ``Interview``,
``OfferLetter`` — see app.api.recruiter) rather than introducing a
second applicant/application system. This package holds the parts
that are genuinely new in V24.3: stage-transition validation, the
immutable ``RecruiterPipelineHistory`` audit trail, and the
statistics/conversion/stale-candidate/bulk-action logic the richer
Kanban board needs. See docs/V24_3_CANDIDATE_PIPELINE.md.
"""
