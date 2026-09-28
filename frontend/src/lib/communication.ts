// V23.4 — thin typed wrapper around /communication/* (app/api/communication.py).
// Preferences reads/writes stay on the existing /notifications/preferences
// endpoint (extended, not duplicated — see app/api/notification_engine.py's
// PreferencesIn) rather than a second preferences call here.

import { api } from "@/lib/api";

export type CommunicationPriority = "LOW" | "NORMAL" | "HIGH" | "URGENT";

export interface CommunicationSummary {
  unread_notifications: number;
  upcoming_interviews: number;
  upcoming_deadlines: number;
  overdue_deadlines: number;
  overdue_tasks: number;
  applications_needing_attention: number;
  new_job_matches: number;
}

export interface ActionItem {
  title: string;
  reason: string;
  priority: CommunicationPriority;
  due_date: string | null;
  source: "INTERVIEW" | "DEADLINE" | "TASK" | "APPLICATION" | "JOB";
  action_url: string;
  kind: string;
}

export interface UpcomingItem {
  type: "INTERVIEW" | "TASK" | "DEADLINE";
  title: string;
  date: string;
  time: string | null;
  action_url: string;
}

export interface UpcomingBuckets {
  TODAY: UpcomingItem[];
  TOMORROW: UpcomingItem[];
  THIS_WEEK: UpcomingItem[];
  LATER: UpcomingItem[];
}

export interface ReminderRecord {
  id: number;
  source_type: string;
  source_id: number;
  reminder_type: string;
  scheduled_for: string;
  status: string;
  priority: CommunicationPriority;
  sent_at: string | null;
}

export const fetchCommunicationSummary = (): Promise<CommunicationSummary> => api("/communication/summary");

export const fetchActionRequired = (limit = 50): Promise<{ actions: ActionItem[] }> =>
  api(`/communication/actions?limit=${limit}`);

export const fetchUpcoming = (days = 14): Promise<UpcomingBuckets> => api(`/communication/upcoming?days=${days}`);

export const fetchReminderHistory = (params: { status?: string; limit?: number } = {}): Promise<{ items: ReminderRecord[] }> => {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  query.set("limit", String(params.limit ?? 50));
  return api(`/communication/reminders?${query.toString()}`);
};
