// V22.1 — thin typed wrapper around /applications (app/api/applications.py),
// same convention as @/lib/recommendations. Every applications
// component should import from here rather than building requests
// itself, so the endpoint paths/param names only live in one place.

import { api } from "@/lib/api";

export const STATUS_VALUES = [
  "SAVED",
  "PLANNING_TO_APPLY",
  "APPLIED",
  "ASSESSMENT",
  "INTERVIEW",
  "OFFER",
  "ACCEPTED",
  "REJECTED",
  "WITHDRAWN",
  "GHOSTED",
] as const;

export type ApplicationStatus = (typeof STATUS_VALUES)[number];

export const STATUS_LABELS: Record<ApplicationStatus, string> = {
  SAVED: "Saved",
  PLANNING_TO_APPLY: "Planning to Apply",
  APPLIED: "Applied",
  ASSESSMENT: "Assessment",
  INTERVIEW: "Interview",
  OFFER: "Offer",
  ACCEPTED: "Accepted",
  REJECTED: "Rejected",
  WITHDRAWN: "Withdrawn",
  GHOSTED: "Ghosted",
};

export interface Application {
  id: number;
  user_id: number;
  job_id: number | null;
  company: string;
  job_title: string;
  job_url: string | null;
  location: string | null;
  employment_type: string | null;
  source: string | null;
  salary: string | null;
  deadline: string | null;
  recruiter_name: string | null;
  recruiter_email: string | null;
  external_reference: string | null;
  status: ApplicationStatus;
  applied_at: string | null;
  next_deadline: string | null;
  notes: string | null;
  status_updated_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface ApplicationHistoryEntry {
  id: number;
  application_id: number;
  old_status: ApplicationStatus | null;
  new_status: ApplicationStatus;
  changed_at: string;
  metadata: Record<string, unknown> | null;
}

export interface ApplicationListResponse {
  items: Application[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApplicationStats {
  total: number;
  by_status: Record<ApplicationStatus, number>;
  recent_activity: {
    application_id: number;
    company: string;
    job_title: string;
    old_status: ApplicationStatus | null;
    new_status: ApplicationStatus;
    changed_at: string;
  }[];
}

/** V22.2 — the richer dashboard surface (superset of ApplicationStats). */
export interface ApplicationDashboard extends ApplicationStats {
  applications_this_week: number;
  applications_this_month: number;
  upcoming_deadlines: UpcomingDeadline[];
  conversion_rates: {
    applied_to_interview: number | null;
    interview_to_offer: number | null;
    offer_to_acceptance: number | null;
  };
}

export type DeadlineUrgency = "upcoming" | "due_soon" | "overdue";

export interface UpcomingDeadline {
  application_id: number;
  company: string;
  job_title: string;
  status: ApplicationStatus;
  deadline: string;
  urgency: DeadlineUrgency;
}

/** Statuses a Kanban board actually has a column for — SAVED precedes
 * active tracking, so it's shown in the list view but not as a
 * draggable Kanban column (see V22_2_APPLICATION_DASHBOARD.md). */
export const KANBAN_STATUSES: ApplicationStatus[] = [
  "PLANNING_TO_APPLY",
  "APPLIED",
  "ASSESSMENT",
  "INTERVIEW",
  "OFFER",
  "ACCEPTED",
  "REJECTED",
  "WITHDRAWN",
  "GHOSTED",
];

/** Statuses that require an explicit reopen to move out of — mirrors
 * app.applications.status.REOPEN_REQUIRED_STATUSES. Used so the UI can
 * confirm with the user before silently reopening a closed application. */
export const REOPEN_REQUIRED_STATUSES: ApplicationStatus[] = ["ACCEPTED", "REJECTED", "WITHDRAWN"];

export interface ApplicationFilters {
  status?: ApplicationStatus;
  company?: string;
  source?: string;
  job_id?: number;
  date_from?: string;
  date_to?: string;
  search?: string;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export interface ExternalApplicationInput {
  company: string;
  job_title: string;
  job_url?: string;
  location?: string;
  employment_type?: string;
  source?: string;
  salary?: string;
  deadline?: string;
  applied_at?: string;
  next_deadline?: string;
  recruiter_name?: string;
  recruiter_email?: string;
  external_reference?: string;
  notes?: string;
  status?: ApplicationStatus;
}

export async function fetchApplications(filters: ApplicationFilters = {}): Promise<ApplicationListResponse> {
  const usp = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") usp.set(key, String(value));
  });
  return api(`/applications?${usp.toString()}`);
}

export async function fetchApplication(id: number): Promise<Application> {
  return api(`/applications/${id}`);
}

export async function fetchApplicationHistory(id: number): Promise<ApplicationHistoryEntry[]> {
  return api(`/applications/${id}/history`);
}

export async function fetchApplicationStats(): Promise<ApplicationStats> {
  return api("/applications/stats");
}

/** V22.2 — GET /applications/dashboard */
export async function fetchApplicationDashboard(): Promise<ApplicationDashboard> {
  return api("/applications/dashboard");
}

/** V22.2 — GET /applications/upcoming-deadlines */
export async function fetchUpcomingDeadlines(days = 30, limit = 20): Promise<UpcomingDeadline[]> {
  const usp = new URLSearchParams({ days: String(days), limit: String(limit) });
  return api(`/applications/upcoming-deadlines?${usp.toString()}`);
}

/** EXTERNAL APPLICATIONS — "Add Application" for a job found outside CareerOS. */
export async function createExternalApplication(input: ExternalApplicationInput): Promise<Application> {
  return api("/applications", { method: "POST", body: JSON.stringify(input) });
}

export async function updateApplication(id: number, patch: Partial<ExternalApplicationInput> & { reopen?: boolean }): Promise<Application> {
  return api(`/applications/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
}

/** STATUS TRANSITION RULES (V22.2) — moving an application out of a
 * terminal status (see REOPEN_REQUIRED_STATUSES) requires reopen=true,
 * or the API returns 409. Callers should confirm with the user first. */
export async function changeApplicationStatus(
  id: number,
  status: ApplicationStatus,
  opts?: { note?: string; reopen?: boolean }
): Promise<Application> {
  return api(`/applications/${id}/status`, {
    method: "POST",
    body: JSON.stringify({ status, note: opts?.note, reopen: opts?.reopen ?? false }),
  });
}

export async function deleteApplication(id: number): Promise<void> {
  await api(`/applications/${id}`, { method: "DELETE" });
}

/** APPLY FROM CAREEROS JOB — "Track Application" (markApplied=false) or
 * "Mark as Applied" (markApplied=true) from a job's own page. */
export async function trackApplicationFromJob(jobId: number, markApplied: boolean): Promise<Application> {
  const usp = new URLSearchParams({ mark_applied: String(markApplied) });
  return api(`/jobs/${jobId}/applications?${usp.toString()}`, { method: "POST" });
}
