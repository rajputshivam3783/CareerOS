"use client";
/**
 * V25.3 — organization hiring intelligence.
 *
 * Every figure here comes from GET/POST /api/v1/organizations/{id}/
 * intelligence*, which the backend authorizes through V25.1
 * organization membership before computing anything. This page never
 * sends its own list of organization ids — it only offers the
 * organizations GET /api/v1/organizations already says this user
 * belongs to, and lets the backend enforce the rest.
 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "180px 1fr 50px", alignItems: "center", gap: 10 }}>
      <span className="muted" style={{ fontSize: 13 }}>{label}</span>
      <div style={{ background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden", height: 14 }}>
        <div style={{ width: `${max ? (value / max) * 100 : 0}%`, background: "var(--blue)", height: "100%" }} />
      </div>
      <span className="muted" style={{ fontSize: 13 }}>{value}</span>
    </div>
  );
}

function InsufficientData({ payload }: { payload: any }) {
  if (!payload || payload.status !== "insufficient_data") return null;
  return <p className="empty">{payload.message}</p>;
}

function AIBlock({ ai, onGenerate, busy }: { ai: any; onGenerate: () => void; busy: boolean }) {
  return (
    <div className="card section">
      <div className="row">
        <h2 style={{ margin: 0 }}>AI insights</h2>
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
      {!ai && <p className="muted">Not generated yet. No individual candidate is ever named in this summary.</p>}
    </div>
  );
}

export default function RecruiterIntelligencePage() {
  const [orgs, setOrgs] = useState<any[]>([]);
  const [orgId, setOrgId] = useState<number | null>(null);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [ai, setAi] = useState<any>(null);
  const [aiBusy, setAiBusy] = useState(false);

  useEffect(() => {
    api("/organizations")
      .then((list) => {
        setOrgs(list || []);
        if (list?.length) setOrgId(list[0].id);
        else setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!orgId) return;
    setLoading(true);
    setError("");
    setAi(null);
    api(`/organizations/${orgId}/intelligence`)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [orgId]);

  async function generateAi() {
    if (!orgId) return;
    setAiBusy(true);
    try {
      const result = await api(`/organizations/${orgId}/ai-insights`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setAi(result.ai);
    } catch (e: any) {
      setAi({ degraded: true, summary: e.message || "AI insights failed." });
    } finally {
      setAiBusy(false);
    }
  }

  if (orgs.length === 0 && !loading) {
    return (
      <main className="container page">
        <span className="eyebrow">Hiring intelligence</span>
        <h1>No organization</h1>
        <p className="muted">You are not a member of any organization yet.</p>
      </main>
    );
  }

  const hiring = data?.hiring || {};
  const overview = hiring.overview || {};
  const funnel = hiring.funnel || {};
  const skillDemand = data?.skill_demand || {};
  const gaps = data?.candidate_pool_gaps || {};
  const difficult = data?.difficult_to_fill || {};

  return (
    <main className="container page">
      <span className="eyebrow">Hiring intelligence</span>
      <div className="pagehead">
        <div>
          <h1>Hiring intelligence</h1>
          <p className="muted">Aggregate figures for your organization only. No other organization&apos;s data appears here.</p>
        </div>
        {orgs.length > 1 && (
          <select className="field" value={orgId ?? ""} onChange={(e) => setOrgId(Number(e.target.value))}>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </select>
        )}
      </div>

      {loading && <p className="loading">Loading…</p>}
      {error && <p className="error">{error}</p>}

      {!loading && !error && data && (
        <>
          {hiring.status === "no_members" ? (
            <p className="empty">{hiring.message}</p>
          ) : (
            <>
              <section className="section">
                <h2>Hiring overview</h2>
                <div className="statgrid">
                  <div className="statcard"><b>{overview.total_jobs ?? "—"}</b><span>Total jobs</span></div>
                  <div className="statcard"><b>{overview.published_jobs ?? "—"}</b><span>Published</span></div>
                  <div className="statcard"><b>{overview.total_applications ?? "—"}</b><span>Applications</span></div>
                  <div className="statcard"><b>{hiring.stale_candidates_count ?? "—"}</b><span>Stale candidates</span></div>
                </div>
              </section>

              {funnel?.steps?.length > 0 && (
                <section className="section">
                  <h2>Pipeline conversion</h2>
                  <p className="muted">{funnel.total_candidates} candidates across your organization&apos;s jobs.</p>
                  <table className="srctable">
                    <thead>
                      <tr>
                        <th scope="col">Stage</th>
                        <th scope="col">Reached</th>
                        <th scope="col">Converted to next</th>
                        <th scope="col">Rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {funnel.steps.map((step: any) => (
                        <tr key={`${step.from_stage}-${step.to_stage}`}>
                          <td>{step.from_stage} → {step.to_stage}</td>
                          <td>{step.from_count}</td>
                          <td>{step.to_count}</td>
                          <td>{step.conversion_rate != null ? `${step.conversion_rate}%` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              )}

              <section className="section">
                <h2>Skill demand</h2>
                <InsufficientData payload={skillDemand} />
                {skillDemand.top_skills?.length > 0 && (
                  <div className="grid2">
                    <div className="card">
                      <b>Most requested skills</b>
                      {skillDemand.top_skills.slice(0, 10).map((row: any) => (
                        <Bar
                          key={row.skill}
                          label={row.display_name}
                          value={row.job_count}
                          max={skillDemand.top_skills[0]?.job_count || 1}
                        />
                      ))}
                    </div>
                    <div className="card">
                      <b>Role distribution</b>
                      {skillDemand.role_distribution?.slice(0, 10).map((row: any) => (
                        <Bar
                          key={row.title}
                          label={row.title}
                          value={row.job_count}
                          max={skillDemand.role_distribution[0]?.job_count || 1}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </section>

              <section className="section">
                <h2>Candidate pool skill gaps</h2>
                <InsufficientData payload={gaps} />
                {gaps.privacy_note && <p className="muted">{gaps.privacy_note}</p>}
                {gaps.gaps?.length > 0 && (
                  <>
                    <p className="muted">{gaps.definition}</p>
                    {gaps.gaps.slice(0, 12).map((row: any) => (
                      <Bar key={row.skill} label={row.display_name} value={row.coverage_pct} max={100} />
                    ))}
                  </>
                )}
              </section>

              <section className="section">
                <h2>Difficult-to-fill roles</h2>
                <p className="muted">{difficult.definition}</p>
                {difficult.jobs?.length === 0 ? (
                  <p className="empty">No roles currently meet this definition.</p>
                ) : (
                  <table className="srctable">
                    <thead>
                      <tr>
                        <th scope="col">Job</th>
                        <th scope="col">Open days</th>
                        <th scope="col">Applications</th>
                        <th scope="col">Why flagged</th>
                      </tr>
                    </thead>
                    <tbody>
                      {difficult.jobs?.map((job: any) => (
                        <tr key={job.job_id}>
                          <td>{job.title}</td>
                          <td>{job.open_days}</td>
                          <td>{job.applications}</td>
                          <td className="muted">{job.reasons.join("; ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              <AIBlock ai={ai} onGenerate={generateAi} busy={aiBusy} />
            </>
          )}
        </>
      )}
    </main>
  );
}
