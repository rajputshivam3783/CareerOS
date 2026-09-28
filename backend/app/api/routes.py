"""Top-level API router — mounts each versioned feature group."""

from fastapi import APIRouter

from app.api.account import router as account
from app.api.admin import router as admin
from app.api.admin_intelligence import router as admin_intelligence
from app.api.admin_observability import router as admin_observability
from app.api.admin_platform import router as admin_platform
from app.api.admin_rbac import router as admin_rbac
from app.api.ai import router as ai
from app.api.application_ai import router as application_ai
from app.api.application_workspace import router as application_workspace
from app.api.applications import router as applications
from app.api.auth import router as auth
from app.api.career_agent import router as career_agent
from app.api.career_copilot import router as career_copilot
from app.api.communication import router as communication
from app.api.company import public_router as company_public
from app.api.company import router as company
from app.api.email_templates import router as email_templates
from app.api.government_core import router as government_core
from app.api.interview_ai import router as interview_ai
from app.api.job_alerts import router as job_alerts
from app.api.notification_engine import router as notification_engine
from app.api.notifications import router as notifications
from app.api.career_intelligence import router as career_intelligence
from app.api.market_intelligence import router as market_intelligence
from app.api.organization_intelligence import router as organization_intelligence
from app.api.organizations import router as organizations
from app.api.partners import router as partners
from app.api.platform import router as platform
from app.api.recommendations import router as recommendations
from app.api.recruiter import router as recruiter
from app.api.recruiter_candidates import router as recruiter_candidates
from app.api.recruiter_pipeline import router as recruiter_pipeline
from app.api.recruiter_analytics import router as recruiter_analytics
from app.api.resume_ai import router as resume_ai
from app.api.search import admin_router as search_admin
from app.api.search import router as search
from app.api.skill_intelligence import router as skill_intelligence
from app.api.source_ops import router as source_ops

router = APIRouter()
router.include_router(auth, prefix="/auth", tags=["V4 Authentication"])
router.include_router(account)  # V25.6 — /account/deactivate, /account/delete
router.include_router(platform, tags=["CareerOS Platform"])
router.include_router(applications, tags=["V22.1 Application Tracking Infrastructure"])
router.include_router(application_workspace, tags=["V22.3 Application Timeline, Notes & Documents"])
router.include_router(application_ai, tags=["V22.4 AI Application Intelligence & Follow-ups"])
router.include_router(partners, prefix="/partners", tags=["V3 Partner Submissions"])
router.include_router(recruiter, prefix="/recruiter", tags=["V9 Recruiter Platform"])
router.include_router(company, prefix="/recruiter", tags=["V18.1 Company Module"])
router.include_router(company_public, tags=["V18.1 Company Directory"])
router.include_router(email_templates, prefix="/recruiter", tags=["V18.5 Email Templates"])
router.include_router(recruiter_candidates, prefix="/recruiter", tags=["V24.2 Candidate Discovery"])
router.include_router(recruiter_pipeline, prefix="/recruiter", tags=["V24.3 Candidate Pipeline & Hiring Workflow"])
router.include_router(recruiter_analytics, prefix="/recruiter", tags=["V24.4 Recruiter Analytics & AI Hiring Intelligence"])
router.include_router(admin, prefix="/admin", tags=["V9 Admin"])
router.include_router(admin_rbac, prefix="/admin", tags=["V17.3 Enterprise RBAC & Admin Controls"])
router.include_router(admin_platform, prefix="/admin", tags=["V25.2 Admin & Platform Governance"])
router.include_router(admin_intelligence, prefix="/admin", tags=["V25.3 Data Intelligence"])
router.include_router(admin_observability, prefix="/admin", tags=["V25.5 Platform Scale, Observability & Reliability"])
router.include_router(government_core, prefix="/government", tags=["V19.1 Government Recruitment Core"])
router.include_router(source_ops, prefix="/government", tags=["V19.2 Official Source Adapter Framework"])
router.include_router(notification_engine, tags=["V19.4 Government Automation & Notification Engine"])
router.include_router(notifications, tags=["V23.1 Notification Infrastructure & Event System"])
router.include_router(ai, tags=["V20.1 AI Infrastructure"])
router.include_router(resume_ai, tags=["V20.2 AI Resume Intelligence"])
router.include_router(career_copilot, tags=["V20.3 AI Career Copilot"])
router.include_router(career_agent, tags=["V25.4 AI Career Agent & Automation"])
router.include_router(interview_ai, tags=["V20.4 AI Interview & Mock Interview System"])
router.include_router(skill_intelligence, tags=["V20.5 AI Learning & Skill Intelligence"])
router.include_router(search, tags=["V21.1 Unified Search Infrastructure"])
router.include_router(search_admin, prefix="/admin", tags=["V21.1 Unified Search Infrastructure"])
router.include_router(recommendations, tags=["V21.3 AI Job Recommendation Engine"])
router.include_router(job_alerts, tags=["V23.3 Smart Job Alerts"])
router.include_router(communication, tags=["V23.4 Communication Center"])
router.include_router(organizations, tags=["V25.1 Multi-Tenant Organizations"])
router.include_router(organization_intelligence, tags=["V25.3 Data Intelligence"])
router.include_router(career_intelligence, tags=["V25.3 Data Intelligence"])
router.include_router(market_intelligence, tags=["V25.3 Data Intelligence"])
