"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const STAGE_LABEL: Record<string, string> = {
  new: "New",
  reviewing: "Reviewing",
  shortlisted: "Shortlisted",
  assessment: "Assessment",
  interview: "Interview",
  offer: "Offer",
  hired: "Hired",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

const RANGE_OPTIONS = [7, 30, 90];

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "140px 1fr 60px", alignItems: "center", gap: 10 }}>
      <span className="muted" style={{ fontSize: 13 }}>{label}</span>
      <div style={{ background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden", height: 14 }}>
        <div style={{ width: `${max ? (value / max) * 100 : 0}%`, background: "var(--blue)", height: "100%" }} />
      </div>
      <span className="muted" style={{ fontSize: 13 }}>{value}</span>
    </div>
  );
}

function AIBlock({ title, ai, onGenerate, busy }: { title: string; ai: any; onGenerate: () => void; busy: boolean }) {
  return (
    <div className="card section">
      <div className="row">
        <h2 style={{ margin: 0 }}>{title}</h2>
        <button className="btn secondary" onClick={onGenerate} disabled={busy}>
          {busy ? "Generating…" : ai ? "Regenerate" : "Generate"}
        </button>
      </div>
      {ai?.degraded && <p className="muted">AI is temporarily unavailable — the data above is unaffected and still accurate.</p>}
      {ai?.flagged && <p className="muted">Part of this output was withheld by the fairness guard — see below.</p>}
      {ai && (
        <>
          <p>{ai.summary}</p>
          {ai.points?.length > 0 && (
            <ul>
              {ai.points.map((p: string, i: number) => (
                <li key={i} className="muted">{p}</li>
              ))}
            </ul>
          )}
        </>
      )}
      {!ai && <p className="muted">Not generated yet.</p>}
    </div>
  );
}

export default function Page() {
  const [overview, setOverview] = useState<any>(null);
  const [pipeline, setPipeline] = useState<any>(null);
  const [trend, setTrend] = useState<any>(null);
  const [trendDays, setTrendDays] = useState(30);
  const [stale, setStale] = useState<any>(null);
  const [staleThreshold, setStaleThreshold] = useState(7);
  const [jobs, setJobs] = useState<any[]>([]);
  const [jobId, setJobId] = useState<number | null>(null);
  const [jobStats, setJobStats] = useState<any>(null);
  const [jobMatches, setJobMatches] = useState<any>(null);
  const [err, setErr] = useState("");

  const [pipelineSummaryAI, setPipelineSummaryAI] = useState<any>(null);
  const [jobInsightsAI, setJobInsightsAI] = useState<any>(null);
  const [comparisonAI, setComparisonAI] = useState<any>(null);
  const [compareIds, setCompareIds] = useState<number[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  async function loadCore() {
    try {
      const [ov, pl, tr, sc, jl] = await Promise.all([
        api("/recruiter/analytics/overview"),
        api("/recruiter/analytics/pipeline"),
        api(`/recruiter/analytics/applications-over-time?days=${trendDays}`),
        api(`/recruiter/analytics/stale-candidates?threshold_days=${staleThreshold}`),
        api("/recruiter/jobs"),
      ]);
      setOverview(ov);
      setPipeline(pl);
      setTrend(tr);
      setStale(sc);
      setJobs(jl);
      if (!jobId && jl.length > 0) setJobId(jl[0].id);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    loadCore();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trendDays, staleThreshold]);

  useEffect(() => {
    if (!jobId) return;
    api(`/recruiter/analytics/jobs/${jobId}`).then(setJobStats).catch((e) => setErr(e.message));
    api(`/recruiter/analytics/jobs/${jobId}/candidates`).then(setJobMatches).catch((e) => setErr(e.message));
    setJobInsightsAI(null);
    setComparisonAI(null);
    setCompareIds([]);
  }, [jobId]);

  async function generatePipelineSummary() {
    setBusy("pipeline");
    try {
      const res = await api("/recruiter/analytics/ai/pipeline-summary", { method: "POST", body: JSON.stringify({}) });
      setPipelineSummaryAI(res.ai);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function generateJobInsights() {
    if (!jobId) return;
    setBusy("job");
    try {
      const res = await api(`/recruiter/analytics/ai/job-insights/${jobId}`, { method: "POST", body: JSON.stringify({}) });
      setJobInsightsAI(res.ai);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function generateComparison() {
    if (!jobId || compareIds.length < 2) return;
    setBusy("compare");
    try {
      const res = await api("/recruiter/analytics/ai/candidate-comparison", {
        method: "POST",
        body: JSON.stringify({ job_id: jobId, candidate_ids: compareIds }),
      });
      setComparisonAI(res.ai);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  function toggleCompare(id: number) {
    setCompareIds((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : prev.length < 8 ? [...prev, id] : prev));
  }

  if (err && !overview) return <main className="container page"><p className="error">{err}</p></main>;
  if (!overview) return <main className="container page">Loading…</main>;

  const maxTrend = Math.max(1, ...trend.series.map((s: any) => s.count));
  const maxStage = Math.max(1, ...Object.values(pipeline?.average_time_in_stage_days || {}).map((v: any) => v || 0));

  return (
    <main className="container page">
      <span className="eyebrow">Recruiter analytics</span>
      <div className="pagehead">
        <div>
          <h1>Hiring analytics &amp; AI intelligence</h1>
          <p className="muted">Deterministic pipeline metrics across all your jobs, plus AI summaries that explain — never decide.</p>
        </div>
        <a className="btn secondary" href="/recruiter">Back to dashboard</a>
      </div>

      {err && <p className="error">{err}</p>}

      {/* 1. KPI cards */}
      <div className="metrics">
        <div className="metric"><b>{overview.total_jobs}</b><span>Total jobs</span></div>
        <div className="metric"><b>{overview.active_jobs}</b><span>Active jobs</span></div>
        <div className="metric"><b>{overview.total_applications}</b><span>Total applications</span></div>
        <div className="metric"><b>{overview.new_applications}</b><span>New</span></div>
        <div className="metric"><b>{overview.candidates_reviewing}</b><span>Reviewing</span></div>
        <div className="metric"><b>{overview.candidates_shortlisted}</b><span>Shortlisted</span></div>
        <div className="metric"><b>{overview.candidates_assessment}</b><span>Assessment</span></div>
        <div className="metric"><b>{overview.candidates_interview}</b><span>Interview</span></div>
        <div className="metric"><b>{overview.offers}</b><span>Offers</span></div>
        <div className="metric"><b>{overview.hired}</b><span>Hired</span></div>
        <div className="metric"><b>{overview.rejected}</b><span>Rejected</span></div>
        <div className="metric"><b>{overview.stale_candidates}</b><span>Stale (&gt;{overview.stale_threshold_days}d)</span></div>
      </div>

      {/* 2. Application trend */}
      <div className="card section">
        <div className="row">
          <h2 style={{ margin: 0 }}>Application trend</h2>
          <div className="row">
            {RANGE_OPTIONS.map((d) => (
              <button key={d} className={d === trendDays ? "btn" : "btn secondary"} onClick={() => setTrendDays(d)}>
                {d}d
              </button>
            ))}
          </div>
        </div>
        {trend.series.every((s: any) => s.count === 0) ? (
          <p className="muted">No applications in this range yet.</p>
        ) : (
          <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 100, marginTop: 12, overflowX: "auto" }}>
            {trend.series.map((s: any) => (
              <div key={s.date} title={`${s.date}: ${s.count}`} style={{ width: 6, height: `${(s.count / maxTrend) * 100}%`, minHeight: s.count ? 2 : 1, background: "var(--blue)", borderRadius: 2 }} />
            ))}
          </div>
        )}
      </div>

      {/* 3. Hiring funnel */}
      <div className="card section">
        <h2>Hiring pipeline funnel</h2>
        {pipeline?.funnel?.steps.map((s: any) => (
          <p key={`${s.from_stage}-${s.to_stage}`} className="muted">
            {STAGE_LABEL[s.from_stage] || s.from_stage} ({s.from_count}) → {STAGE_LABEL[s.to_stage] || s.to_stage} ({s.to_count}):{" "}
            {s.conversion_rate === null ? "no data yet" : `${s.conversion_rate}%`}
          </p>
        ))}
      </div>

      {/* 4. Time in stage / bottleneck */}
      <div className="card section">
        <h2>Time &amp; bottlenecks</h2>
        <p className="muted">{pipeline?.bottleneck_observation}</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
          {Object.entries(pipeline?.average_time_in_stage_days || {}).map(([stage, days]: [string, any]) => (
            <Bar key={stage} label={STAGE_LABEL[stage] || stage} value={days || 0} max={maxStage} />
          ))}
        </div>
        <div className="grid2" style={{ marginTop: 12 }}>
          <p className="muted">Avg. time to first review: {pipeline?.average_time_to_first_review_days ?? "not enough data"} days</p>
          <p className="muted">Avg. application → interview: {pipeline?.average_time_application_to_interview_days ?? "not enough data"} days</p>
          <p className="muted">Avg. interview → offer: {pipeline?.average_time_interview_to_offer_days ?? "not enough data"} days</p>
          <p className="muted">Avg. offer → hired: {pipeline?.average_time_offer_to_hired_days ?? "not enough data"} days</p>
          <p className="muted">Overall time to hire: {pipeline?.overall_time_to_hire_days ?? "not enough data"} days</p>
        </div>
      </div>

      <AIBlock title="AI pipeline summary" ai={pipelineSummaryAI} onGenerate={generatePipelineSummary} busy={busy === "pipeline"} />

      {/* 5. Job performance */}
      <div className="card section">
        <div className="row">
          <h2 style={{ margin: 0 }}>Job performance</h2>
          <select className="field" value={jobId ?? ""} onChange={(e) => setJobId(Number(e.target.value))}>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>{j.title}</option>
            ))}
          </select>
        </div>
        {jobs.length === 0 && <p className="muted">Post a job to see per-job analytics.</p>}
        {jobStats && (
          <>
            <div className="metrics">
              <div className="metric"><b>{jobStats.applications}</b><span>Applications</span></div>
              <div className="metric"><b>{jobStats.interview_count}</b><span>Interviews</span></div>
              <div className="metric"><b>{jobStats.offer_count}</b><span>Offers</span></div>
              <div className="metric"><b>{jobStats.hire_count}</b><span>Hires</span></div>
              <div className="metric"><b>{jobStats.rejection_count}</b><span>Rejections</span></div>
              <div className="metric"><b>{jobStats.withdrawal_count}</b><span>Withdrawals</span></div>
            </div>
            <p className="muted">
              Avg. days in pipeline (active candidates): {jobStats.average_days_in_pipeline_active_candidates ?? "not enough data"}
            </p>
            <p className="muted">
              Job views, apply clicks and source data: not tracked by this platform yet.
            </p>
          </>
        )}
      </div>

      {/* 6. Candidate match distribution */}
      {jobMatches && (
        <div className="card section">
          <h2>Candidate match distribution</h2>
          {jobMatches.candidates_scored === 0 ? (
            <p className="muted">No applicants to score yet for this job.</p>
          ) : (
            <>
              <div className="metrics">
                <div className="metric"><b>{jobMatches.distribution.high}</b><span>High match (≥75%)</span></div>
                <div className="metric"><b>{jobMatches.distribution.medium}</b><span>Medium match</span></div>
                <div className="metric"><b>{jobMatches.distribution.low}</b><span>Low match</span></div>
                <div className="metric"><b>{jobMatches.average_skill_coverage_pct ?? "—"}%</b><span>Avg. skill coverage</span></div>
              </div>
              {jobMatches.most_commonly_missing_skills?.length > 0 && (
                <p className="muted">
                  Most commonly missing skills: {jobMatches.most_commonly_missing_skills.map((m: any) => `${m.skill} (${m.candidates_missing})`).join(", ")}
                </p>
              )}
              <h3>Compare candidates</h3>
              <p className="muted">Select 2-8 candidates, then generate an evidence-based AI comparison.</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {jobMatches.candidates.map((c: any) => (
                  <label key={c.id} className="checkbox-label">
                    <input type="checkbox" checked={compareIds.includes(c.id)} onChange={() => toggleCompare(c.id)} />
                    {c.full_name} — match {c.match_score}% — {c.top_skills.join(", ") || "no skills listed"}
                  </label>
                ))}
              </div>
              <button className="btn" disabled={compareIds.length < 2 || busy === "compare"} onClick={generateComparison} style={{ marginTop: 10 }}>
                {busy === "compare" ? "Comparing…" : "Compare selected candidates"}
              </button>
            </>
          )}
        </div>
      )}

      {jobId && <AIBlock title="AI job insights" ai={jobInsightsAI} onGenerate={generateJobInsights} busy={busy === "job"} />}
      {comparisonAI && <AIBlock title="AI candidate comparison" ai={comparisonAI} onGenerate={generateComparison} busy={busy === "compare"} />}

      {/* 7. Stale candidates */}
      <div className="card section">
        <div className="row">
          <h2 style={{ margin: 0 }}>Stale candidates</h2>
          <label className="field-label">
            Threshold (days)
            <input
              className="field"
              type="number"
              min={0}
              value={staleThreshold}
              onChange={(e) => setStaleThreshold(Math.max(0, Number(e.target.value)))}
            />
          </label>
        </div>
        {stale?.candidates.length === 0 ? (
          <p className="muted">No stale candidates at this threshold.</p>
        ) : (
          stale?.candidates.map((c: any) => (
            <div key={`${c.job_id}-${c.applicant_id}`} style={{ borderTop: "1px solid var(--line)", padding: "10px 0" }}>
              <b>{c.job_title}</b> — {STAGE_LABEL[c.pipeline_stage] || c.pipeline_stage} — {c.days_inactive} day(s) inactive
              <p className="muted">{c.suggested_action}</p>
              <a className="linkbtn" href={`/recruiter/jobs/${c.job_id}/pipeline`}>Open pipeline</a>
            </div>
          ))
        )}
      </div>
    </main>
  );
}
