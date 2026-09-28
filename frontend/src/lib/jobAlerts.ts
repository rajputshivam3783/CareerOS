import { api } from "@/lib/api";

export type JobAlert = {
  id: number;
  name: string;
  keywords: string | null;
  job_title: string | null;
  skills: string | null;
  location: string | null;
  remote_preference: string | null;
  employment_type: string | null;
  experience_level: string | null;
  salary_min: number | null;
  salary_max: number | null;
  job_category: string | null;
  govt_private_preference: string | null;
  company: string | null;
  source: string | null;
  frequency: "INSTANT" | "DAILY" | "WEEKLY";
  min_relevance_score: number | null;
  use_profile_personalization: boolean;
  enabled: boolean;
  last_run_at: string | null;
  last_run_status: string | null;
  last_match_count: number;
  created_at: string;
  updated_at: string;
};

export type JobAlertMatch = {
  job_id: number;
  title: string;
  organization: string;
  location: string | null;
  job_type: string | null;
  employment_type: string | null;
  salary: string | null;
  posted_date: string | null;
  relevance_score: number;
  match_reasons: string[];
  already_delivered: boolean;
};

export type JobAlertRun = {
  id: number;
  started_at: string;
  completed_at: string | null;
  status: string;
  candidates_scanned: number;
  jobs_matched: number;
  notifications_created: number;
  emails_queued: number;
  error_summary: string | null;
};

export type JobAlertFormInput = Partial<{
  name: string;
  keywords: string;
  job_title: string;
  skills: string;
  location: string;
  remote_preference: string;
  employment_type: string;
  experience_level: string;
  salary_min: number;
  salary_max: number;
  job_category: string;
  govt_private_preference: string;
  company: string;
  source: string;
  frequency: string;
  min_relevance_score: number;
  use_profile_personalization: boolean;
  enabled: boolean;
}>;

export const listJobAlerts = (): Promise<JobAlert[]> => api("/job-alerts");
export const getJobAlert = (id: number): Promise<JobAlert> => api(`/job-alerts/${id}`);
export const createJobAlert = (payload: JobAlertFormInput): Promise<JobAlert> =>
  api("/job-alerts", { method: "POST", body: JSON.stringify(payload) });
export const updateJobAlert = (id: number, payload: JobAlertFormInput): Promise<JobAlert> =>
  api(`/job-alerts/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteJobAlert = (id: number): Promise<null> => api(`/job-alerts/${id}`, { method: "DELETE" });
export const enableJobAlert = (id: number): Promise<JobAlert> => api(`/job-alerts/${id}/enable`, { method: "POST" });
export const disableJobAlert = (id: number): Promise<JobAlert> => api(`/job-alerts/${id}/disable`, { method: "POST" });
export const getJobAlertMatches = (id: number): Promise<{ items: JobAlertMatch[] }> => api(`/job-alerts/${id}/matches`);
export const getJobAlertHistory = (id: number): Promise<{ items: JobAlertRun[] }> => api(`/job-alerts/${id}/history`);
export const previewNewJobAlert = (payload: JobAlertFormInput): Promise<{ items: JobAlertMatch[] }> =>
  api("/job-alerts/preview", { method: "POST", body: JSON.stringify(payload) });
export const runJobAlertNow = (id: number): Promise<JobAlertRun> => api(`/job-alerts/${id}/run-now`, { method: "POST" });
