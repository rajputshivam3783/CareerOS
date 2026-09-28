// V21.3/V21.4 — thin, typed wrapper around GET/POST /job-recommendations/*,
// same convention as @/lib/search (V21.1): every recommendation
// component imports from here rather than building requests itself,
// so the endpoint paths/param names only live in one place (see
// backend/app/api/recommendations.py for the source of truth this
// mirrors).
//
// Mounted at /job-recommendations, not /recommendations — that path
// belongs to a different, older, simpler endpoint
// (backend/app/api/platform.py, V6) that this does not replace.

import { api } from "@/lib/api";

export type RecommendationCategory =
  | "Best Match"
  | "Strong Match"
  | "Skill-Building Opportunity"
  | "Career Growth Opportunity"
  | "Recently Posted Match"
  | "Deadline Approaching"
  | "Potential Match";

export interface GovernmentRelevance {
  label: string;
  reasons: string[];
  confidence: number;
  source_url: string | null;
  disclaimer: string;
}

export interface RankedRecommendation {
  job_id: number;
  title: string;
  organization: string;
  job_type: string;
  location: string;
  salary: string | null;
  employment_type: string | null;
  work_mode: string | null;
  deadline: string | null;
  notification_url: string | null;
  apply_url: string | null;
  posted_date: string;

  overall_score: number;
  category: RecommendationCategory;
  category_tags: RecommendationCategory[];
  eligibility_bucket: string;
  score_breakdown: Record<string, number>;
  unavailable_components: string[];

  explanation_summary: string;
  matched_skills: string[];
  missing_skills: string[];
  missing_skills_in_progress: string[];
  experience_fit: string;
  location_fit: string;
  career_goal_fit: string;
  negative_reasons: string[];

  already_saved: boolean;
  already_applied: boolean;

  government_relevance: GovernmentRelevance | null;

  // V21.4 — PERSONALIZED RANKING / "Why This Job" / "Personalized Match"
  personalized_match: boolean;
  personalization_reasons: string[];
}

export interface RecommendationsResponse {
  items: RankedRecommendation[];
  total_before_limit: number;
  is_cold_start: boolean;
  from_cache: boolean;
  generated_at: string;
  // V21.4
  personalization_enabled: boolean;
}

export interface RecommendationPreferences {
  include_government: boolean;
  include_private: boolean;
  include_internships: boolean;
  include_apprenticeships: boolean;
  preferred_employment_types: string[];
  diversity_level: "low" | "balanced" | "high";
  // V21.4 — USER CONTROLS: Personalized Recommendations ON/OFF
  personalization_enabled: boolean;
}

// V21.4 — non-raw summary of what's currently influencing the feed
// (PRIVACY: never raw event history, only categorized top signals).
export interface PersonalizationSummary {
  personalization_enabled: boolean;
  top_signals: Record<string, string[]>;
}

export type FeedbackType = "interested" | "not_interested" | "dismiss" | "not_relevant";
export type RecommendationEventType =
  | "impression" | "open" | "save" | "apply" | "dismiss" | "not_relevant"
  | "interested" | "not_interested" | "share";

export const CATEGORY_LABELS: Record<RecommendationCategory, string> = {
  "Best Match": "Best Match",
  "Strong Match": "Strong Match",
  "Skill-Building Opportunity": "Skill-Building Opportunity",
  "Career Growth Opportunity": "Career Growth Opportunity",
  "Recently Posted Match": "Recently Posted",
  "Deadline Approaching": "Deadline Approaching",
  "Potential Match": "Potential Match",
};

export const ALL_CATEGORIES: RecommendationCategory[] = [
  "Best Match",
  "Strong Match",
  "Skill-Building Opportunity",
  "Career Growth Opportunity",
  "Recently Posted Match",
  "Deadline Approaching",
];

/** GET /job-recommendations — "Jobs For You". */
export async function fetchRecommendations(opts?: {
  limit?: number;
  category?: RecommendationCategory;
  refresh?: boolean;
}): Promise<RecommendationsResponse> {
  const usp = new URLSearchParams();
  usp.set("limit", String(opts?.limit ?? 20));
  if (opts?.category) usp.set("category", opts.category);
  if (opts?.refresh) usp.set("refresh", "true");
  return api(`/job-recommendations?${usp.toString()}`);
}

/** GET /job-recommendations/{jobId}/explanation — always scored fresh,
 * so it's safe to call even if the cached feed hasn't refreshed yet. */
export async function fetchExplanation(jobId: number): Promise<RankedRecommendation> {
  return api(`/job-recommendations/${jobId}/explanation`);
}

/** FEEDBACK LOOP — Interested / Not Interested / Dismiss / Not
 * Relevant. Does not save or apply — use the existing bookmarks/
 * applications flows for that (see @/lib/bookmarks). Recording the
 * corresponding analytics/behavior event happens server-side as part
 * of this call (see app.recommendations.feedback.record_feedback) —
 * callers should NOT also call logRecommendationEvent for the same
 * feedback_type afterward (V21.4: doing so used to mislabel the event
 * as "impression" for interested/not_interested; removed). */
export async function submitFeedback(jobId: number, feedbackType: FeedbackType): Promise<void> {
  await api(`/job-recommendations/${jobId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ feedback_type: feedbackType }),
  });
}

/** ANALYTICS + BEHAVIORAL SIGNALS — impression/open/save/apply/share
 * signal for one specific job. Best-effort: a failure here should
 * never block the candidate's actual action. */
export async function logRecommendationEvent(jobId: number, eventType: RecommendationEventType): Promise<void> {
  try {
    await api(`/job-recommendations/${jobId}/event`, {
      method: "POST",
      body: JSON.stringify({ event_type: eventType }),
    });
  } catch {
    /* analytics logging is best-effort */
  }
}

/** V21.4 — BEHAVIORAL SIGNALS not scoped to one job: filter_usage
 * (which filter dimension changed), share, or feed_view. `filters` is
 * short structured metadata only — never free-text search input. */
export async function logGenericEvent(eventType: "filter_usage" | "share", filters?: Record<string, unknown>, jobId?: number): Promise<void> {
  try {
    await api("/job-recommendations/events", {
      method: "POST",
      body: JSON.stringify({ event_type: eventType, job_id: jobId ?? null, filters: filters ?? null }),
    });
  } catch {
    /* analytics logging is best-effort */
  }
}

export async function fetchRecommendationPreferences(): Promise<RecommendationPreferences> {
  return api("/job-recommendations/preferences");
}

export async function updateRecommendationPreferences(
  patch: Partial<RecommendationPreferences>
): Promise<RecommendationPreferences> {
  return api("/job-recommendations/preferences", { method: "PUT", body: JSON.stringify(patch) });
}

// --- V21.4 USER CONTROLS ---

/** GET /job-recommendations/personalization — ON/OFF state plus a
 * categorized (never raw) view of what's currently influencing the
 * feed, e.g. {"company": ["acme corp"], "skill": ["python"]}. */
export async function fetchPersonalizationSummary(): Promise<PersonalizationSummary> {
  return api("/job-recommendations/personalization");
}

/** PUT /job-recommendations/personalization — the ON/OFF toggle
 * itself. Turning this off does not affect explicit stated
 * preferences (skills, career goal, location) — only the learned
 * behavioral component. */
export async function setPersonalizationEnabled(enabled: boolean): Promise<RecommendationPreferences> {
  return api("/job-recommendations/personalization", {
    method: "PUT",
    body: JSON.stringify({ personalization_enabled: enabled }),
  });
}

/** "Reset Recommendation Preferences" — reverts stated settings
 * (opportunity-type filters, diversity level, personalization toggle)
 * to defaults. Does not clear learned behavior — see
 * clearRecommendationHistory below. */
export async function resetRecommendationPreferences(): Promise<RecommendationPreferences> {
  return api("/job-recommendations/reset", { method: "POST" });
}

/** "Clear Recommendation History" — deletes learned behavioral
 * signals and raw event history. Explicit per-job dismiss/not-relevant
 * verdicts are untouched (those are intentional, not inferred). */
export async function clearRecommendationHistory(): Promise<{ behavior_signals_cleared: number; events_cleared: number }> {
  return api("/job-recommendations/clear-history", { method: "POST" });
}
