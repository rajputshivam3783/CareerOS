"use client";

// V21.3 — one "Jobs For You" recommendation card. Mirrors the layout
// SearchResults.tsx already established (pill row, title link,
// org/location, actions row) and adds the EXPLANATIONS/NEGATIVE
// REASONS/FEEDBACK LOOP pieces the spec asks for: an expandable "Why
// this job" panel and Interested/Not Interested/Dismiss buttons.

import { useState } from "react";
import {
  CATEGORY_LABELS,
  FeedbackType,
  RankedRecommendation,
  logGenericEvent,
  logRecommendationEvent,
  submitFeedback,
} from "@/lib/recommendations";

const CATEGORY_CLASS: Record<string, string> = {
  "Best Match": "rec-badge-best",
  "Strong Match": "rec-badge-strong",
  "Skill-Building Opportunity": "rec-badge-skillbuild",
  "Career Growth Opportunity": "rec-badge-growth",
  "Recently Posted Match": "rec-badge-recent",
  "Deadline Approaching": "rec-badge-deadline",
  "Potential Match": "rec-badge-potential",
};

export default function RecommendationCard({
  item,
  onDismissed,
}: {
  item: RankedRecommendation;
  onDismissed?: (jobId: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState<FeedbackType | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleFeedback(type: FeedbackType) {
    if (busy) return;
    setBusy(true);
    try {
      // V21.4: submitFeedback already records the corresponding
      // behavioral/analytics event server-side (see
      // app.recommendations.feedback.record_feedback) — no separate
      // logRecommendationEvent call needed here anymore (the old call
      // mislabeled interested/not_interested as "impression").
      await submitFeedback(item.job_id, type);
      setFeedbackSent(type);
      if ((type === "dismiss" || type === "not_relevant") && onDismissed) onDismissed(item.job_id);
    } finally {
      setBusy(false);
    }
  }

  function handleOpen() {
    logRecommendationEvent(item.job_id, "open");
  }

  // Job Share "where supported" — falls back to copying the link when
  // the Web Share API isn't available (desktop browsers).
  async function handleShare() {
    const url = `${location.origin}/jobs/${item.job_id}`;
    try {
      if (navigator.share) {
        await navigator.share({ title: item.title, url });
      } else {
        await navigator.clipboard.writeText(url);
      }
      logGenericEvent("share", undefined, item.job_id);
    } catch {
      /* user cancelled the share sheet, or clipboard denied — not an error */
    }
  }

  if (feedbackSent === "dismiss" || feedbackSent === "not_relevant") {
    return null;
  }

  return (
    <article className="card rec-card">
      <div className="row">
        <span className={`pill ${CATEGORY_CLASS[item.category] || ""}`}>{CATEGORY_LABELS[item.category] ?? item.category}</span>
        <span className="pill">{item.job_type}</span>
        <span className="rec-score" title="Overall match score">
          {item.overall_score}% match
        </span>
        {item.personalized_match && (
          <span className="pill rec-badge-personalized" title="This recommendation is influenced by your activity on CareerOS">
            Personalized Match
          </span>
        )}
      </div>

      <h2>
        <a href={`/jobs/${item.job_id}`} onClick={handleOpen}>
          {item.title}
        </a>
      </h2>
      <p className="strong">{item.organization}</p>
      <p>
        {item.location}
        {item.work_mode ? ` · ${item.work_mode}` : ""}
        {item.employment_type ? ` · ${item.employment_type}` : ""}
      </p>
      {item.salary && <p className="muted">{item.salary}</p>}
      {item.deadline && (
        <p>
          Deadline: <b>{item.deadline}</b>
        </p>
      )}

      {(item.already_saved || item.already_applied) && (
        <div className="row">
          {item.already_saved && <span className="pill verified">Saved</span>}
          {item.already_applied && <span className="pill verified">Applied</span>}
        </div>
      )}

      {item.personalized_match && item.personalization_reasons.length > 0 && (
        <p className="muted rec-why-this-job">
          <b>Why this job:</b> {item.personalization_reasons.join("; ")}
        </p>
      )}
      <p className="muted">{item.explanation_summary}</p>

      {item.government_relevance && (
        <p className="muted">
          <b>{item.government_relevance.label}.</b> {item.government_relevance.disclaimer}
        </p>
      )}

      <button className="linkbtn" onClick={() => setExpanded((v) => !v)}>
        {expanded ? "Hide details" : "Why this job?"}
      </button>

      {expanded && (
        <div className="section">
          {item.matched_skills.length > 0 && (
            <div className="tagrow">
              {item.matched_skills.map((s) => (
                <span className="tag rec-tag-matched" key={s}>
                  {s}
                </span>
              ))}
            </div>
          )}
          {item.missing_skills.length > 0 && (
            <div className="tagrow">
              {item.missing_skills.map((s) => (
                <span className="tag rec-tag-missing" key={s}>
                  {s}
                  {item.missing_skills_in_progress.includes(s) ? " (learning)" : ""}
                </span>
              ))}
            </div>
          )}
          <p className="muted">Experience fit: {item.experience_fit}</p>
          <p className="muted">Location fit: {item.location_fit}</p>
          <p className="muted">Career goal fit: {item.career_goal_fit}</p>
          {item.negative_reasons.length > 0 && (
            <ul className="muted">
              {item.negative_reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="actions">
        <a className="btn secondary" href={`/jobs/${item.job_id}`} onClick={handleOpen}>
          View details
        </a>
        <button className="linkbtn" disabled={busy} onClick={() => handleFeedback("interested")}>
          {feedbackSent === "interested" ? "Marked interested ✓" : "Interested"}
        </button>
        <button className="linkbtn" disabled={busy} onClick={() => handleFeedback("not_interested")}>
          Not interested
        </button>
        <button className="linkbtn danger" disabled={busy} onClick={() => handleFeedback("dismiss")}>
          Dismiss
        </button>
        <button className="linkbtn danger" disabled={busy} onClick={() => handleFeedback("not_relevant")}>
          Not relevant
        </button>
        <button className="linkbtn" onClick={handleShare}>
          Share
        </button>
      </div>
    </article>
  );
}
