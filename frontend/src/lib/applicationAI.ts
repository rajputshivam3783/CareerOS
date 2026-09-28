// V22.4 — thin typed wrapper around /applications/{id}/ai/* (app/api/
// application_ai.py), same convention as @/lib/applicationWorkspace.
// Every AI-generating call can come back "degraded" (AI unavailable) —
// callers should render that state, not treat it as an error.

import { api } from "@/lib/api";

export interface HealthResult {
  score: number;
  label: "Healthy" | "Needs Attention" | "At Risk" | "Stale";
  reasons: string[];
}

export interface NextBestAction {
  action: string;
  reason: string;
  timing: string;
}

export interface FollowUpTiming {
  timing: "Not needed" | "Consider soon" | "Follow up today" | "Follow up urgently";
  reason: string;
}

export interface Risk {
  risk: string;
  severity: "low" | "medium" | "high";
  reason: string;
  recommended_action: string;
}

export interface ActionPlanItem {
  bucket: "TODAY" | "NEXT_2_DAYS" | "BEFORE_INTERVIEW" | "AFTER_INTERVIEW";
  title: string;
  priority: string;
  reason: string;
  due_date: string | null;
}

export interface Narrative {
  summary: string;
  encouragement_or_caution: string;
  talking_points: string[];
  degraded: boolean;
}

export interface ApplicationOverview {
  health: HealthResult;
  priority: "Low" | "Medium" | "High" | "Critical";
  next_best_action: NextBestAction;
  follow_up: FollowUpTiming;
  risks: Risk[];
  action_plan: ActionPlanItem[];
  signals: {
    days_since_last_activity: number | null;
    deadline_days_left: number | null;
    overdue_task_count: number;
    has_upcoming_interview: boolean;
  };
  narrative: Narrative | null;
  narrative_generated_at: string | null;
}

export async function fetchOverview(applicationId: number): Promise<ApplicationOverview> {
  return api(`/applications/${applicationId}/ai/overview`);
}

export async function analyze(applicationId: number, force = false): Promise<ApplicationOverview & { from_cache: boolean }> {
  return api(`/applications/${applicationId}/ai/analyze`, { method: "POST", body: JSON.stringify({ force }) });
}

export interface FollowUpDraft {
  subject: string;
  body: string;
  tone: "PROFESSIONAL" | "CONCISE" | "FRIENDLY";
  degraded: boolean;
  from_cache: boolean;
}

export async function generateFollowUp(applicationId: number, tone: FollowUpDraft["tone"], force = false): Promise<FollowUpDraft> {
  return api(`/applications/${applicationId}/ai/follow-up`, { method: "POST", body: JSON.stringify({ tone, force }) });
}

export interface InterviewPrep {
  topics_to_prepare: string[];
  likely_areas: string[];
  suggested_questions: string[];
  candidate_specific_prep: string[];
  questions_to_ask_interviewer: string[];
  note: string;
  degraded: boolean;
  interview_id: number;
  from_cache: boolean;
}

export async function generateInterviewPrep(applicationId: number, interviewId?: number, force = false): Promise<InterviewPrep> {
  return api(`/applications/${applicationId}/ai/interview-prep`, {
    method: "POST",
    body: JSON.stringify({ interview_id: interviewId, force }),
  });
}
