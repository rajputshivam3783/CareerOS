# CareerOS Recruiter Guide

A walkthrough of the recruiter-facing ATS, in the order you'd typically use it.

## 1. Getting recruiter access

Recruiter accounts aren't self-serve: register a normal account, then an
admin grants the `recruiter` role via `POST /admin/users/{id}/role`. Once
approved, sign in at `/recruiter-login`.

## 2. Set up your company profile

Go to **Company profile** (`/recruiter/company`) and fill in name, logo,
banner, description, industry, size, founded year, location, and social
links. Add office branches under **Branches**. A newly-created profile
starts `unverified`; editing name/industry/description/size/location after
verification sends it back to `pending` review.

## 3. Build your team roster

**Manage team** (`/recruiter/company/team`) lets you add other *existing*
recruiter accounts to your company's roster by email â€” they must already
be registered and approved as recruiters. Anyone on the team can now see
and manage every job, applicant, interview, and offer owned by anyone
else on the same team (not just their own) â€” company profile settings
and email templates remain owner-only.

## 4. Post a job

From the recruiter dashboard, **Create a job** with title, organization,
type, location, work mode, industry, experience, vacancies, salary,
deadline, qualification, and description. New listings start in `draft`
and move through `review` â†’ `published` via the existing approval
workflow. From a job's detail view you can also **clone**, **close**,
**reopen**, or **archive** it.

## 5. Manage the applicant pipeline

Open a job's **pipeline** view (link from `/recruiter/jobs`) for a
drag-and-drop Kanban board: drag a candidate card between columns
(applied â†’ shortlisted â†’ screening â†’ interview â†’ technical_round â†’
hr_round â†’ offer â†’ accepted / rejected / withdrawn) to move them â€”
the move saves automatically and rolls back if it fails. Click a card to
open the full candidate profile, where you can also leave private notes
visible only to your team.

## 6. Schedule interviews

From an applicant's profile, add an interview: type (phone / online /
onsite / technical / HR / panel), date, time, duration, interviewer, and
meeting link. Update its status as it happens.

## 7. Send offers

Create an offer for an applicant (draft), then send it. Track status as
sent â†’ accepted / rejected / expired, or withdraw a sent offer.

## 8. Customize email templates

**Email templates** (`/recruiter/company/email-templates`) gives you five
editable templates: application received, interview invitation, interview
reminder, offer, and rejection.

- Click a template chip to switch between the five types.
- Edit the subject and body directly. Click a variable chip (e.g.
  `{{candidate_name}}`) to insert it at your cursor position in the body.
- **Preview with sample data** renders the template against realistic
  sample values so you can see exactly what a candidate would see.
- **Reset to default** discards your edits and restores the built-in
  wording for that template type.
- A dot (â€¢) next to a template's name in the chip list means you've
  customized it away from the default.

Note: editing a template here changes its stored text; it does not by
itself send anything. Wiring these templates into the actual outbound
email flow (via Notifications) is planned for a later version.

## 9. Export and analytics

Export an applicant list to **CSV** or **Excel** from a job's applicants
view â€” same data, pick whichever format you want to open. The
**Analytics** page (`/recruiter/analytics`) shows jobs, applicants,
conversion, time-to-hire, pipeline, and offer-acceptance metrics.

## 10. Where things live (for support/debugging)

| What | URL |
|---|---|
| Dashboard | `/recruiter` |
| Job management | `/recruiter/jobs` |
| Company profile | `/recruiter/company` |
| Team roster | `/recruiter/company/team` |
| Email templates | `/recruiter/company/email-templates` |
| Analytics | `/recruiter/analytics` |

