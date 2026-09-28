# CareerOS

CareerOS is a full-stack career platform built with **FastAPI, SQLAlchemy, Next.js, TypeScript, and PostgreSQL**. It combines job discovery, government recruitment tracking, applications, resume/ATS intelligence, career guidance, interview preparation, recruiter workflows, notifications, recommendations, analytics, and AI-assisted career features.

## Current Build

**V25.7 — Government Recruitment & AI Integrated Build**

The current build brings together the major platform layers developed across V1–V25:

- Job discovery, search, filtering, and applications
- Government recruitment ingestion and lifecycle tracking
- Candidate authentication, profiles, and application management
- Recruiter accounts, job posting, applicant pipeline, and analytics
- Resume analysis, ATS analysis, and job matching
- Career intelligence, recommendations, and learning/skill features
- Interview preparation and AI-assisted interview workflows
- Notifications, alerts, email infrastructure, and reminders
- Multi-tenant organizations and role-based access control
- Platform administration, audit, security, and compliance controls
- Search, analytics, reliability, health/readiness, and operational tooling
- AI-assisted career features with controlled and validated application boundaries

This is a production-oriented integrated build. Actual production readiness still depends on the deployment environment, database, secrets, email provider, monitoring, live-source validation, and final security/performance testing.

## Feature Overview

| Area | Capability |
|---|---|
| Jobs | Private and government job discovery, search, filtering, and details |
| Government Jobs | Official-source ingestion, normalization, deduplication, enrichment, review |
| Applications | Application tracking, status management, deadlines, and workspace |
| Resume / ATS | Resume parsing, skill extraction, ATS analysis, and job matching |
| Career AI | Career guidance, skill-gap analysis, and recommendations |
| Interview | Interview practice, questions, evaluation, and reports |
| Recruiter | Recruiter workspace, job management, applicants, and pipeline |
| Organizations | Multi-tenant organizations, memberships, and tenant isolation |
| Administration | Platform administration, moderation, audit, and system controls |
| Search | Unified search, ranking, permissions, and recent searches |
| Notifications | In-app notifications, alerts, email infrastructure, and reminders |
| Learning | Skill intelligence, learning paths, assessments, and resources |
| Security | Authentication, RBAC, sessions, rate limiting, and audit logging |
| Reliability | Health/readiness, dead-letter tracking, and operational tooling |
| AI | Controlled AI-assisted features across selected workflows |

## Architecture

```text
                 Next.js / TypeScript
                         |
                         v
                    FastAPI API
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
      PostgreSQL     Ingestion       AI Services
                       Pipeline
                          |
                          v
                Configured Official Sources
```

## Repository Structure

```text
CareerOS/
├── backend/
│   ├── app/
│   ├── migrations/
│   ├── scripts/
│   ├── tests/
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   ├── package.json
│   └── .env.example
├── docs/
│   ├── ai/
│   ├── ats/
│   ├── career/
│   ├── government/
│   ├── infrastructure/
│   ├── interview/
│   ├── learning/
│   ├── personalization/
│   ├── platform/
│   ├── recommendation/
│   ├── recruiter/
│   ├── releases/
│   ├── search/
│   └── security/
├── docker-compose.yml
├── docker-compose.production.yml
├── START_CAREEROS.bat
├── CHANGELOG.md
├── KNOWN_LIMITATIONS.md
├── PROJECT_STATUS.md
└── ROADMAP.md
```

## Quick Start — Windows

Requirements:

- Python 3.13+
- Node.js / npm
- Git

Run:

```powershell
.\START_CAREEROS.bat
```

Typical local URLs:

```text
Frontend: http://localhost:3000
Backend:  http://127.0.0.1:8000
API Docs: http://127.0.0.1:8000/docs
```

## Environment Configuration

Secrets and machine-specific configuration are intentionally excluded from Git.

```powershell
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env
```

Configure local values in `backend/.env`.

**Never commit `.env` files, API keys, passwords, JWT secrets, or database credentials.**

For production, configure secrets through the deployment platform rather than committing them to the repository.

## PostgreSQL

PostgreSQL is the intended production database.

Configure:

```env
DATABASE_URL=postgresql://username:password@host:5432/careeros
```

Run the project's migrations against the production database before starting the application. Review migrations before applying them to an existing production database.

## Government Job Ingestion

CareerOS includes a government recruitment ingestion framework with:

- Configurable source registry
- Official-source adapters
- HTML, metadata, PDF, and feed collectors
- Normalization and deduplication
- Enrichment
- Admin review and publishing controls
- Ingestion health and error tracking
- Scheduled ingestion

Government websites can change HTML, certificates, access rules, rate limits, and APIs without notice. Individual sources must therefore be validated against their current official endpoints before production use.

Failed or unverified collection is not treated as successful ingestion, and records should pass the configured review/publishing workflow.

## AI Features

AI is used as an assisted capability across selected CareerOS features such as career guidance, resume intelligence, interview workflows, recommendations, and job-data enrichment.

AI output is assisted information, not an authoritative decision. Where deterministic calculations exist, they remain the source of truth; AI can explain or assist with those results.

AI provider credentials belong in environment variables and are never stored in the repository.

## Responsible AI

CareerOS is designed to assist people rather than make final employment decisions automatically.

Human review remains important for hiring, recruitment, eligibility, and other consequential decisions.

## Security

Before public deployment:

- Generate strong unique `JWT_SECRET` and `ADMIN_API_KEY` values
- Use PostgreSQL
- Configure the correct production frontend origin
- Configure SMTP for real email delivery
- Configure `METRICS_TOKEN` when metrics are exposed
- Configure trusted proxy settings appropriately
- Review CORS and security headers
- Keep `.env` and credentials out of Git
- Complete the production security checklist

Security documentation:

- `docs/SECURITY.md`
- `docs/SECURITY_CONTROL_MATRIX.md`
- `docs/SECURITY_INCIDENT_RESPONSE.md`
- `docs/PRODUCTION_SECURITY_CHECKLIST.md`
- `docs/VULNERABILITY_MANAGEMENT.md`
- `docs/DATA_RETENTION_AND_DELETION.md`
- `docs/API_SECURITY_INVENTORY.md`
- `docs/security/SECURITY_ARCHITECTURE.md`
- `docs/security/RBAC_ARCHITECTURE.md`
- `docs/security/SESSION_MANAGEMENT.md`

## Health & Operations

The backend provides:

```text
GET /live
GET /ready
GET /metrics
```

Production deployment should also include appropriate logging, monitoring, backups, recovery procedures, TLS, secret management, and infrastructure-level security controls.

## Version History

Use these files for current project documentation:

- `PROJECT_STATUS.md` — current implementation status
- `CHANGELOG.md` — version history
- `ROADMAP.md` — roadmap and remaining work
- `KNOWN_LIMITATIONS.md` — known limitations
- `docs/releases/` — release-specific documentation

Major milestones:

- **V1–V10:** Core platform, ingestion, identity, eligibility, career intelligence, applications, career growth, recruiter platform, scale and hardening
- **V16–V17:** Authentication, security, RBAC, sessions, and platform hardening
- **V18:** Recruiter ATS and applicant workflows
- **V19:** Government recruitment and notification infrastructure
- **V20:** AI infrastructure and career intelligence
- **V21:** Unified search, recommendations, and personalization
- **V22:** Application tracking and application intelligence
- **V23:** Notifications, email, alerts, and communication
- **V24:** Recruiter workspace and hiring intelligence
- **V25:** Multi-tenancy, platform governance, data intelligence, AI career workflows, reliability, security, and compliance
- **V25.7:** Government ingestion/enrichment integration and current project stabilization

## Current Limitations

Production deployment still requires environment-specific work, including:

- Production PostgreSQL provisioning
- Production secrets and environment variables
- SMTP/email provider configuration
- Domain and HTTPS configuration
- Live government-source validation
- Monitoring and alerting infrastructure
- Backup and recovery configuration
- Final dependency, security, and performance testing

See `KNOWN_LIMITATIONS.md` for details.

## License

Add the project's intended license here before public distribution.
