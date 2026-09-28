"use client";

import { useEffect, useState } from "react";
import { SkeletonLines } from "@/components/Skeleton";
import {
  ApplicationOverview,
  FollowUpDraft,
  InterviewPrep,
  analyze,
  fetchOverview,
  generateFollowUp,
  generateInterviewPrep,
} from "@/lib/applicationAI";
import { createTask } from "@/lib/applicationWorkspace";

const HEALTH_CLASS: Record<string, string> = {
  Healthy: "badge-success",
  "Needs Attention": "badge-progress",
  "At Risk": "badge-negative",
  Stale: "badge-disabled",
};

const PRIORITY_CLASS: Record<string, string> = {
  Low: "badge-disabled",
  Medium: "badge-progress",
  High: "badge-negative",
  Critical: "badge-negative",
};

const SEVERITY_CLASS: Record<string, string> = { low: "badge-disabled", medium: "badge-progress", high: "badge-negative" };

const BUCKET_LABELS: Record<string, string> = {
  TODAY: "Today",
  NEXT_2_DAYS: "Next 2 Days",
  BEFORE_INTERVIEW: "Before Interview",
  AFTER_INTERVIEW: "After Interview",
};
const BUCKET_ORDER = ["TODAY", "NEXT_2_DAYS", "BEFORE_INTERVIEW", "AFTER_INTERVIEW"];

export default function AIInsightsTab({ applicationId }: { applicationId: number }) {
  const [overview, setOverview] = useState<ApplicationOverview | null>(null);
  const [error, setError] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [addedTasks, setAddedTasks] = useState<Set<number>>(new Set());

  async function load() {
    try {
      setOverview(await fetchOverview(applicationId));
    } catch (e: any) {
      setError(e.message || "Could not load AI Application Intelligence.");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId]);

  async function handleRefresh() {
    setAnalyzing(true);
    setError("");
    try {
      const result = await analyze(applicationId, true);
      setOverview(result);
    } catch (e: any) {
      setError(e.message || "Could not refresh the AI analysis.");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleAddToTasks(item: ApplicationOverview["action_plan"][number], index: number) {
    try {
      await createTask(applicationId, { title: item.title, description: item.reason, due_at: item.due_date || undefined });
      setAddedTasks((prev) => new Set(prev).add(index));
    } catch (e: any) {
      setError(e.message || "Could not add this to your tasks.");
    }
  }

  if (overview === null) return <SkeletonLines count={5} />;

  const groupedPlan = BUCKET_ORDER.map((bucket) => ({
    bucket,
    items: overview.action_plan.map((item, i) => ({ ...item, _index: i })).filter((item) => item.bucket === bucket),
  })).filter((g) => g.items.length > 0);

  return (
    <div>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="row" style={{ marginBottom: 16 }}>
        <div>
          <span className="eyebrow">AI application intelligence</span>
          <p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>
            {overview.narrative_generated_at
              ? `Last analyzed ${new Date(overview.narrative_generated_at).toLocaleString()}`
              : "Not yet analyzed by AI — the figures below are computed directly."}
          </p>
        </div>
        <button className="btn" onClick={handleRefresh} disabled={analyzing}>
          {analyzing ? "Analyzing..." : "Refresh AI Analysis"}
        </button>
      </div>

      <div className="grid2" style={{ marginBottom: 16 }}>
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Application Health</h2>
          <p style={{ fontSize: 28, fontWeight: 800, margin: "4px 0" }}>
            {overview.health.score}
            <span style={{ fontSize: 16, fontWeight: 500 }}>/100</span>{" "}
            <span className={`badge ${HEALTH_CLASS[overview.health.label] || ""}`}>{overview.health.label}</span>
          </p>
          <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
            {overview.health.reasons.map((r, i) => (
              <li key={i} style={{ fontSize: 13 }}>
                {r}
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h2 style={{ marginTop: 0 }}>
            Priority <span className={`badge ${PRIORITY_CLASS[overview.priority] || ""}`}>{overview.priority}</span>
          </h2>
          <h3 style={{ marginBottom: 4, fontSize: 14 }}>Next Best Action</h3>
          <p style={{ margin: "0 0 4px", fontWeight: 700 }}>{overview.next_best_action.action}</p>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            {overview.next_best_action.reason}
          </p>
          <p style={{ margin: "4px 0 0", fontSize: 13 }}>
            <b>Suggested timing:</b> {overview.next_best_action.timing}
          </p>

          <h3 style={{ margin: "14px 0 4px", fontSize: 14 }}>Follow-up Recommendation</h3>
          <p style={{ margin: 0, fontWeight: 700 }}>{overview.follow_up.timing}</p>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            {overview.follow_up.reason}
          </p>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ marginTop: 0 }}>AI Analysis</h2>
        {overview.narrative ? (
          overview.narrative.degraded ? (
            <p className="muted">AI analysis is currently unavailable. {overview.narrative.summary}</p>
          ) : (
            <div>
              <span className="pill" style={{ marginBottom: 8, display: "inline-block" }}>
                AI-generated
              </span>
              <p style={{ margin: "4px 0" }}>{overview.narrative.summary}</p>
              {overview.narrative.encouragement_or_caution && <p style={{ margin: "4px 0" }}>{overview.narrative.encouragement_or_caution}</p>}
              {overview.narrative.talking_points.length > 0 && (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                  {overview.narrative.talking_points.map((t, i) => (
                    <li key={i} style={{ fontSize: 13 }}>
                      {t}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )
        ) : (
          <p className="muted">Click &quot;Refresh AI Analysis&quot; for an AI-written explanation of the figures above.</p>
        )}
      </div>

      {overview.risks.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ marginTop: 0 }}>Risk Factors</h2>
          {overview.risks.map((r, i) => (
            <div key={i} className="wk-item">
              <div className="wk-item-main">
                <b>
                  {r.risk} <span className={`badge ${SEVERITY_CLASS[r.severity] || ""}`}>{r.severity}</span>
                </b>
                <p style={{ margin: "4px 0" }}>{r.reason}</p>
                <p className="muted" style={{ margin: 0, fontSize: 13 }}>
                  <b>Recommended:</b> {r.recommended_action}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {groupedPlan.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ marginTop: 0 }}>AI Action Plan</h2>
          {groupedPlan.map((group) => (
            <div key={group.bucket} style={{ marginBottom: 14 }}>
              <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>{BUCKET_LABELS[group.bucket]}</h3>
              {group.items.map((item) => (
                <div key={item._index} className="wk-item">
                  <div className="wk-item-main">
                    <b>{item.title}</b>
                    <p className="muted" style={{ margin: "2px 0", fontSize: 13 }}>
                      {item.priority} priority — {item.reason}
                      {item.due_date ? ` · Due ${item.due_date}` : ""}
                    </p>
                  </div>
                  <div className="wk-item-actions">
                    <button
                      className="linkbtn"
                      disabled={addedTasks.has(item._index)}
                      onClick={() => handleAddToTasks(item, item._index)}
                    >
                      {addedTasks.has(item._index) ? "Added \u2713" : "Add to My Tasks"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      <FollowUpGenerator applicationId={applicationId} />
      <InterviewPrepGenerator applicationId={applicationId} />
    </div>
  );
}

function FollowUpGenerator({ applicationId }: { applicationId: number }) {
  const [tone, setTone] = useState<FollowUpDraft["tone"]>("PROFESSIONAL");
  const [draft, setDraft] = useState<FollowUpDraft | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleGenerate() {
    setBusy(true);
    setError("");
    try {
      const result = await generateFollowUp(applicationId, tone, true);
      setDraft(result);
      setSubject(result.subject);
      setBody(result.body);
    } catch (e: any) {
      setError(e.message || "Could not generate a follow-up draft.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h2 style={{ marginTop: 0 }}>Smart Follow-up</h2>
      {error && <p className="error">{error}</p>}
      <div className="row" style={{ justifyContent: "flex-start", gap: 10, marginBottom: 10 }}>
        <select className="field" style={{ maxWidth: 200 }} value={tone} onChange={(e) => setTone(e.target.value as FollowUpDraft["tone"])}>
          <option value="PROFESSIONAL">Professional</option>
          <option value="CONCISE">Concise</option>
          <option value="FRIENDLY">Friendly</option>
        </select>
        <button className="btn" onClick={handleGenerate} disabled={busy}>
          {busy ? "Generating..." : "Generate Follow-up"}
        </button>
      </div>

      {draft && (
        <div>
          {draft.degraded ? (
            <p className="muted">{draft.body}</p>
          ) : (
            <div className="form">
              <span className="pill" style={{ marginBottom: 6, display: "inline-block" }}>
                AI-generated draft — edit before using
              </span>
              <label className="field-label">
                Subject
                <input className="field" value={subject} onChange={(e) => setSubject(e.target.value)} />
              </label>
              <label className="field-label">
                Body
                <textarea className="field" rows={10} value={body} onChange={(e) => setBody(e.target.value)} />
              </label>
              <p className="muted" style={{ fontSize: 12 }}>
                CareerOS never sends this automatically — copy it into your own email client when you&apos;re ready.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function InterviewPrepGenerator({ applicationId }: { applicationId: number }) {
  const [prep, setPrep] = useState<InterviewPrep | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleGenerate() {
    setBusy(true);
    setError("");
    try {
      setPrep(await generateInterviewPrep(applicationId, undefined, true));
    } catch (e: any) {
      setError(e.message || "Could not generate interview preparation.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Interview Preparation</h2>
      {error && <p className="error">{error}</p>}
      <button className="btn" onClick={handleGenerate} disabled={busy}>
        {busy ? "Preparing..." : "Prepare for Interview"}
      </button>

      {prep && (
        <div style={{ marginTop: 12 }}>
          {prep.degraded ? (
            <p className="muted">{prep.note}</p>
          ) : (
            <div>
              <span className="pill" style={{ marginBottom: 8, display: "inline-block" }}>
                AI-generated preparation suggestions — not guaranteed interview questions
              </span>
              <PrepList title="Topics to prepare" items={prep.topics_to_prepare} />
              <PrepList title="Likely interview areas" items={prep.likely_areas} />
              <PrepList title="Suggested practice questions" items={prep.suggested_questions} />
              <PrepList title="Candidate-specific preparation" items={prep.candidate_specific_prep} />
              <PrepList title="Questions to ask the interviewer" items={prep.questions_to_ask_interviewer} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PrepList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <h3 style={{ fontSize: 14, margin: "0 0 4px" }}>{title}</h3>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {items.map((it, i) => (
          <li key={i} style={{ fontSize: 13 }}>
            {it}
          </li>
        ))}
      </ul>
    </div>
  );
}
