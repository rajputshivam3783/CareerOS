// V22.3 — thin typed wrapper around /applications/{id}/{notes,interviews,
// tasks,documents,timeline} (app/api/application_workspace.py), same
// convention as @/lib/applications. Kept as its own file rather than
// growing applications.ts further, since these are five distinct child
// resources rather than the Application entity itself.

import { api, apiDownload } from "@/lib/api";

// ---------------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------------

export interface ApplicationNote {
  id: number;
  application_id: number;
  content: string;
  created_at: string;
  updated_at: string | null;
}

export async function fetchNotes(applicationId: number): Promise<ApplicationNote[]> {
  return api(`/applications/${applicationId}/notes`);
}

export async function createNote(applicationId: number, content: string): Promise<ApplicationNote> {
  return api(`/applications/${applicationId}/notes`, { method: "POST", body: JSON.stringify({ content }) });
}

export async function updateNote(applicationId: number, noteId: number, content: string): Promise<ApplicationNote> {
  return api(`/applications/${applicationId}/notes/${noteId}`, { method: "PATCH", body: JSON.stringify({ content }) });
}

export async function deleteNote(applicationId: number, noteId: number): Promise<void> {
  await api(`/applications/${applicationId}/notes/${noteId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Interviews
// ---------------------------------------------------------------------------

export const INTERVIEW_TYPES = ["PHONE", "VIDEO", "TECHNICAL", "HR", "MANAGERIAL", "ASSESSMENT", "ONSITE", "OTHER"] as const;
export type InterviewType = (typeof INTERVIEW_TYPES)[number];

export const INTERVIEW_RESULTS = ["SCHEDULED", "COMPLETED", "PASSED", "FAILED", "CANCELLED", "RESCHEDULED"] as const;
export type InterviewResult = (typeof INTERVIEW_RESULTS)[number];

export interface ApplicationInterview {
  id: number;
  application_id: number;
  interview_type: InterviewType;
  round_name: string | null;
  scheduled_at: string | null;
  duration_minutes: number | null;
  interviewer_name: string | null;
  interviewer_email: string | null;
  meeting_url: string | null;
  location: string | null;
  notes: string | null;
  result: InterviewResult;
  created_at: string;
  updated_at: string | null;
}

export interface InterviewInput {
  interview_type: InterviewType;
  round_name?: string;
  scheduled_at?: string;
  duration_minutes?: number;
  interviewer_name?: string;
  interviewer_email?: string;
  meeting_url?: string;
  location?: string;
  notes?: string;
  result?: InterviewResult;
}

export async function fetchInterviews(applicationId: number): Promise<ApplicationInterview[]> {
  return api(`/applications/${applicationId}/interviews`);
}

export async function createInterview(applicationId: number, input: InterviewInput): Promise<ApplicationInterview> {
  return api(`/applications/${applicationId}/interviews`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateInterview(applicationId: number, interviewId: number, patch: Partial<InterviewInput>): Promise<ApplicationInterview> {
  return api(`/applications/${applicationId}/interviews/${interviewId}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export async function deleteInterview(applicationId: number, interviewId: number): Promise<void> {
  await api(`/applications/${applicationId}/interviews/${interviewId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------

export interface ApplicationTask {
  id: number;
  application_id: number;
  title: string;
  description: string | null;
  due_at: string | null;
  completed: boolean;
  completed_at: string | null;
  overdue: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface TaskInput {
  title: string;
  description?: string;
  due_at?: string;
}

export async function fetchTasks(applicationId: number, includeCompleted = true): Promise<ApplicationTask[]> {
  return api(`/applications/${applicationId}/tasks?include_completed=${includeCompleted}`);
}

export async function createTask(applicationId: number, input: TaskInput): Promise<ApplicationTask> {
  return api(`/applications/${applicationId}/tasks`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateTask(
  applicationId: number,
  taskId: number,
  patch: Partial<TaskInput> & { completed?: boolean }
): Promise<ApplicationTask> {
  return api(`/applications/${applicationId}/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export async function setTaskCompleted(applicationId: number, taskId: number, completed: boolean): Promise<ApplicationTask> {
  return updateTask(applicationId, taskId, { completed });
}

export async function deleteTask(applicationId: number, taskId: number): Promise<void> {
  await api(`/applications/${applicationId}/tasks/${taskId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export const DOCUMENT_CATEGORIES = ["RESUME", "COVER_LETTER", "PORTFOLIO", "CERTIFICATE", "ASSESSMENT", "OFFER_LETTER", "OTHER"] as const;
export type DocumentCategory = (typeof DOCUMENT_CATEGORIES)[number];

export interface ApplicationDocument {
  id: number;
  application_id: number;
  category: DocumentCategory;
  original_filename: string;
  file_size: number;
  mime_type: string | null;
  uploaded_at: string;
}

export async function fetchDocuments(applicationId: number): Promise<ApplicationDocument[]> {
  return api(`/applications/${applicationId}/documents`);
}

export async function uploadDocument(applicationId: number, category: DocumentCategory, file: File): Promise<ApplicationDocument> {
  const form = new FormData();
  form.append("category", category);
  form.append("file", file);
  return api(`/applications/${applicationId}/documents`, { method: "POST", body: form });
}

export async function downloadDocument(applicationId: number, doc: ApplicationDocument): Promise<void> {
  await apiDownload(`/applications/${applicationId}/documents/${doc.id}/download`, doc.original_filename);
}

export async function deleteDocument(applicationId: number, documentId: number): Promise<void> {
  await api(`/applications/${applicationId}/documents/${documentId}`, { method: "DELETE" });
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------
// Timeline
// ---------------------------------------------------------------------------

export interface TimelineEntry {
  event_type: string;
  title: string;
  description: string | null;
  metadata: Record<string, unknown> | null;
  occurred_at: string;
  source: "status_history" | "event";
  source_id: number;
}

export async function fetchTimeline(applicationId: number, order: "asc" | "desc" = "desc"): Promise<TimelineEntry[]> {
  return api(`/applications/${applicationId}/timeline?order=${order}`);
}
