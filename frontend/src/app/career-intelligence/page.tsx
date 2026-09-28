"use client";
/**
 * V25.3 — candidate career intelligence.
 *
 * Every figure here comes from GET /api/v1/career-intelligence/* and
 * is the candidate's own authorized data plus aggregate, labelled
 * CareerOS job-market activity. No opaque "career score" is rendered
 * anywhere — every ratio shown carries the formula that produced it,
 * taken straight from the API response.
 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "160px 1fr 50px", alignItems: "center", gap: 10 }}>
      <span className="muted" style={{ fontSize: 13 }}>{label}</span>
      <div style={{ background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden", height: 14 }}>
        <div style={{ width: `${max ? (value / max) * 100 : 0}%`, background: "var(--blue)", height: "100%" }} />
      </div>
      <span className="muted" style={{ fontSize: 13 }}>{value}</span>
    </div>
  );
}

function InsufficientData({ payload }: { payload: any }) {
  return (
    <p className="empty">
      {payload?.message || "Insufficient CareerOS data to report this reliably."}
      {typeof payload?.sample_size === "number" && (
        <span className="muted">
          {" "}
          ({payload.sample_size} observed, {payload.required_sample_size} required)
        </span>
      )}
    </p>
  );
}

function AIBlock({ ai, onGenerate, busy }: { ai: any; onGenerate: () => void; busy: boolean }) {
  return (
    <div className="card section">
      <div className="row">
        <h2 style={{ margin: 0 }}>AI summary</h2>
        <button className="btn secondary" onClick={onGenerate} disabled={busy}>
          {busy ? "Generating…" : ai ? "Regenerate" : "Generate"}
        </button>
      </div>
      {ai?.degraded && (
        <p className="muted">AI is temporarily unavailable — the figures above are unaffected and still accurate.</p>
      )}
      {ai?.flagged && <p className="muted">Part of this output was withheld by the fairness guard.</p>}
      {ai?.summary && (
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
      {!ai && <p className="muted">Not generated yet. AI only explains the figures already shown — it never calculates them.</p>}
    </div>
  );
}

export default function CareerIntelligencePage() {
  const [overview, setOverview] = useState<any>(null);
  const [gaps, setGaps] = useState<any>(null);
  const [roleInput, setRoleInput] = useState("");
  const [activeRole, setActiveRole] = useState<string | undefined>(undefined);
  const [availableRoles, setAvailableRoles] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [ai, setAi] = useState<any>(null);
  const [aiBusy, setAiBusy] = useState(false);

  async function load(role?: string) {
    setLoading(true);
    setError("");
    try {
      const qs = role ? `?role=${encodeURIComponent(role)}` : "";
      const [ov, gp] = await Promise.all([
        api(`/career-intelligence/overview${qs}`),
        api(`/career-intelligence/skill-gaps${qs}`),
      ]);
      setOverview(ov);
      setGaps(gp);
      if (!role && ov?.target_role?.role) setActiveRole(ov.target_role.role);
    } catch (e: any) {
      setError(e.message || "Could not load career intelligence.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    api("/career-intelligence/roles")
      .then((r) => setAvailableRoles(r.roles || []))
      .catch(() => undefined);
  }, []);

  async function generateAi() {
    setAiBusy(true);
    try {
      const result = await api("/career-intelligence/ai-summary", {
        method: "POST",
        body: JSON.stringify({ role: activeRole || null }),
      });
      setAi(result.ai);
    } catch (e: any) {
      setAi({ degraded: true, summary: e.message || "AI summary failed." });
    } finally {
      setAiBusy(false);
    }
  }

  function selectRole(role: string) {
    setActiveRole(role);
    setAi(null);
    load(role);
  }

  if (loading) return <main className="container page"><p className="loading">Loading your career intelligence…</p></main>;
  if (error) return <main className="container page"><p className="error">{error}</p></main>;
  if (!overview) return null;

  const target = overview.target_role || {};
  const activity = overview.application_activity || {};
  const conversion = activity.interview_conversion || {};
  const completeness = overview.profile_completeness || {};

  return (
    <main className="container page">
      <span className="eyebrow">Career intelligence</span>
      <div className="pagehead">
        <div>
          <h1>Your career overview</h1>
          <p className="muted">
            Built from your own CareerOS data and aggregate, CareerOS-only job activity. Nothing here reflects any
            other candidate.
          </p>
        </div>
      </div>

      <section className="section">
        <h2>Profile completeness</h2>
        <p className="muted">{completeness.formula}</p>
        <div className="statgrid">
          {(completeness.items || []).map((item: any) => (
            <div className="statcard" key={item.field}>
              <b>{item.complete ? "✓" : "—"}</b>
              <span>{item.field.replace(/_/g, " ")}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <h2>Your skills</h2>
        {overview.skills?.skill_count ? (
          <div className="filters">
            {overview.skills.skills.map((s: string) => (
              <span className="chip" key={s}>{s}</span>
            ))}
          </div>
        ) : (
          <p className="empty">No skills yet — add them to your profile or upload a resume.</p>
        )}
        <p className="muted">{overview.skills?.note}</p>
      </section>

      <section className="section">
        <h2>Application activity</h2>
        <div className="statgrid">
          <div className="statcard"><b>{activity.total_applications}</b><span>Applications</span></div>
          <div className="statcard"><b>{activity.saved_jobs}</b><span>Saved jobs</span></div>
          <div className="statcard"><b>{activity.hired_count}</b><span>Hired</span></div>
          <div className="statcard">
            <b>{conversion.interview_rate_pct != null ? `${conversion.interview_rate_pct}%` : "—"}</b>
            <span>Interview conversion</span>
          </div>
        </div>
        {conversion.interview_rate_pct == null && <InsufficientData payload={conversion} />}
        {conversion.formula && <p className="muted">{conversion.formula}</p>}

        {activity.pipeline_distribution?.length > 0 && (
          <>
            <h3>Pipeline distribution</h3>
            {activity.pipeline_distribution.map((row: any) => (
              <Bar
                key={row.key}
                label={row.key.replace(/_/g, " ")}
                value={row.count}
                max={Math.max(...activity.pipeline_distribution.map((r: any) => r.count))}
              />
            ))}
          </>
        )}
      </section>

      <section className="section">
        <div className="row">
          <h2>Target role</h2>
        </div>
        <p className="muted">{target.source_description}</p>

        <form
          className="search"
          onSubmit={(e) => {
            e.preventDefault();
            if (roleInput.trim()) selectRole(roleInput.trim());
          }}
        >
          <input
            className="field"
            placeholder="Type a role, e.g. Backend Developer"
            value={roleInput}
            onChange={(e) => setRoleInput(e.target.value)}
            aria-label="Target role"
          />
          <button className="btn" type="submit">Set role</button>
        </form>

        {availableRoles.length > 0 && (
          <div className="filters">
            {availableRoles.slice(0, 10).map((r: any) => (
              <button key={r.title} type="button" className="chip" onClick={() => selectRole(r.title)}>
                {r.title} ({r.job_count})
              </button>
            ))}
          </div>
        )}

        {gaps?.status === "no_target_role" && <p className="empty">{gaps.message}</p>}
        {gaps?.status === "insufficient_data" && (
          <>
            <InsufficientData payload={gaps} />
            <p className="muted">{gaps.message}</p>
          </>
        )}

        {gaps?.status === "ok" && (
          <>
            <p className="muted">
              Matching against {gaps.matching_jobs} published CareerOS job(s) titled like &quot;{target.role}&quot;.
              {gaps.corpus_truncated && " (Showing a sample of the largest matching set.)"}
            </p>
            <p className="muted">{gaps.requirement_definition}</p>

            <div className="grid2">
              <div className="card">
                <b>Skill coverage: {gaps.coverage?.coverage_pct}%</b>
                <p className="muted">{gaps.coverage?.formula}</p>
                <h3>Matched skills</h3>
                <div className="filters">
                  {gaps.coverage?.matched_skills?.length ? (
                    gaps.coverage.matched_skills.map((s: any) => (
                      <span className="chip chip-active" key={s.skill}>{s.display_name}</span>
                    ))
                  ) : (
                    <span className="muted">None yet</span>
                  )}
                </div>
                <h3>Missing skills</h3>
                <div className="filters">
                  {gaps.coverage?.missing_skills?.length ? (
                    gaps.coverage.missing_skills.map((s: any) => (
                      <span className="chip" key={s.skill}>{s.display_name}</span>
                    ))
                  ) : (
                    <span className="muted">None — you cover every reference skill found.</span>
                  )}
                </div>
              </div>

              <div className="card">
                <b>Frequently requested skills for this role on CareerOS</b>
                {gaps.frequently_requested_skills?.map((row: any) => (
                  <Bar
                    key={row.skill}
                    label={row.display_name}
                    value={row.job_count}
                    max={gaps.frequently_requested_skills[0]?.job_count || 1}
                  />
                ))}
                <p className="muted">{gaps.skill_data_coverage?.note}</p>
              </div>
            </div>

            {(gaps.experience_requirements_stated?.length > 0 || gaps.education_requirements_stated?.length > 0) && (
              <div className="grid2">
                <div className="card">
                  <b>Experience requirements stated</b>
                  {gaps.experience_requirements_stated?.map((row: any, i: number) => (
                    <p key={i} className="muted">{row.requirement} — {row.job_count} job(s)</p>
                  ))}
                </div>
                <div className="card">
                  <b>Education requirements stated</b>
                  {gaps.education_requirements_stated?.map((row: any, i: number) => (
                    <p key={i} className="muted">{row.requirement} — {row.job_count} job(s)</p>
                  ))}
                </div>
              </div>
            )}
            <p className="muted">{gaps.experience_gap_note}</p>
            <p className="muted">{gaps.outcome_disclaimer}</p>
          </>
        )}
      </section>

      <AIBlock ai={ai} onGenerate={generateAi} busy={aiBusy} />
    </main>
  );
}
