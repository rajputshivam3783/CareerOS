"use client";
/**
 * V25.3 — admin platform intelligence.
 *
 * Every figure comes from GET /admin/intelligence*, which V25.2's
 * platform-admin authorization gates (PLATFORM_ANALYTICS). Everything
 * shown is labelled CareerOS platform activity — never described as
 * an external market statistic, because CareerOS holds no such
 * dataset.
 */
import { useEffect, useState } from "react";
import { AdminShell, AsyncState } from "@/components/admin/AdminShell";
import { adminApi } from "@/lib/adminApi";

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

function AIBlock({ ai, onGenerate, busy }: { ai: any; onGenerate: () => void; busy: boolean }) {
  return (
    <div className="card section">
      <div className="row">
        <h2 style={{ margin: 0 }}>AI summary</h2>
        <button className="btn secondary" type="button" onClick={onGenerate} disabled={busy}>
          {busy ? "Generating…" : ai ? "Regenerate" : "Generate"}
        </button>
      </div>
      {ai?.degraded && <p className="muted">AI is temporarily unavailable — the figures above are unaffected.</p>}
      {ai?.summary && (
        <>
          <p>{ai.summary}</p>
          {ai.points?.length > 0 && (
            <ul>{ai.points.map((p: string, i: number) => <li key={i} className="muted">{p}</li>)}</ul>
          )}
        </>
      )}
      {!ai && <p className="muted">Not generated yet.</p>}
    </div>
  );
}

export default function AdminIntelligencePage() {
  const [days, setDays] = useState(90);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [ai, setAi] = useState<any>(null);
  const [aiBusy, setAiBusy] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError("");
    adminApi(`/intelligence?days=${days}`)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [days]);

  async function generateAi() {
    setAiBusy(true);
    try {
      const result = await adminApi("/intelligence/ai-summary", { method: "POST", body: JSON.stringify({ days }) });
      setAi(result.ai);
    } catch (e: any) {
      setAi({ degraded: true, summary: e.message });
    } finally {
      setAiBusy(false);
    }
  }

  return (
    <AdminShell title="Platform intelligence" description="Aggregate CareerOS platform activity — never an external market claim.">
      <div className="filters">
        {[30, 90, 180, 365].map((option) => (
          <button
            key={option}
            type="button"
            className={`chip${days === option ? " chip-active" : ""}`}
            onClick={() => setDays(option)}
          >
            Last {option} days
          </button>
        ))}
      </div>

      <AsyncState loading={loading} error={error} empty={!data} emptyMessage="No intelligence data available.">
        {data && (
          <>
            <p className="muted">{data.scope_note}</p>

            <section className="section">
              <h2>Categories</h2>
              <div className="grid2">
                <div className="card">
                  <b>Jobs by category</b>
                  {data.categories?.jobs_by_category?.map((row: any) => (
                    <Bar key={row.key} label={row.key} value={row.count} max={data.categories.jobs_by_category[0]?.count || 1} />
                  ))}
                </div>
                <div className="card">
                  <b>Applications by category</b>
                  {data.categories?.applications_by_category?.map((row: any) => (
                    <Bar key={row.key} label={row.key} value={row.count} max={data.categories.applications_by_category[0]?.count || 1} />
                  ))}
                </div>
              </div>
            </section>

            <section className="section">
              <h2>Skills</h2>
              {data.skills?.status === "insufficient_data" ? (
                <p className="empty">{data.skills.message}</p>
              ) : (
                <>
                  <p className="muted">{data.skills?.note}</p>
                  {data.skills?.top_skills?.map((row: any) => (
                    <Bar key={row.skill} label={row.display_name} value={row.job_count} max={data.skills.top_skills[0]?.job_count || 1} />
                  ))}
                </>
              )}
            </section>

            <section className="section">
              <h2>Roles</h2>
              {data.roles?.slice(0, 15).map((row: any) => (
                <Bar key={row.title} label={row.title} value={row.job_count} max={data.roles[0]?.job_count || 1} />
              ))}
            </section>

            <section className="section">
              <h2>Organizations</h2>
              <table className="srctable">
                <thead>
                  <tr>
                    <th scope="col">Organization</th>
                    <th scope="col">Status</th>
                    <th scope="col">Jobs</th>
                    <th scope="col">Applications</th>
                  </tr>
                </thead>
                <tbody>
                  {data.organizations?.map((row: any) => (
                    <tr key={row.organization_id}>
                      <td>{row.name}</td>
                      <td>{row.active ? "Active" : "Suspended"}</td>
                      <td>{row.jobs}</td>
                      <td>{row.applications}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="section">
              <h2>Candidates</h2>
              <div className="statgrid">
                <div className="statcard"><b>{data.candidates?.active_candidates}</b><span>Active candidates</span></div>
                <div className="statcard"><b>{data.candidates?.candidates_with_profile}</b><span>With profile</span></div>
                <div className="statcard"><b>{data.candidates?.candidates_with_resume}</b><span>With resume</span></div>
                <div className="statcard"><b>{data.candidates?.candidates_who_applied}</b><span>Have applied</span></div>
              </div>
              <p className="muted">{data.candidates?.note}</p>
            </section>

            <section className="section">
              <h2>Ingestion activity</h2>
              {data.ingestion?.sources?.length === 0 ? (
                <p className="empty">No ingestion runs in this window.</p>
              ) : (
                <table className="srctable">
                  <thead>
                    <tr>
                      <th scope="col">Source</th>
                      <th scope="col">Runs</th>
                      <th scope="col">Jobs created</th>
                      <th scope="col">Skipped</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.ingestion?.sources?.map((row: any) => (
                      <tr key={row.source_name}>
                        <td>{row.source_name}</td>
                        <td>{row.runs}</td>
                        <td>{row.jobs_created}</td>
                        <td>{row.records_skipped}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <AIBlock ai={ai} onGenerate={generateAi} busy={aiBusy} />
          </>
        )}
      </AsyncState>
    </AdminShell>
  );
}
