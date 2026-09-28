"use client";
import { safeHref } from "@/lib/safe";

import { useEffect, useState } from "react";
import { API } from "@/lib/api";
import { api } from "@/lib/api";

const JOB_TYPES = ["All", "Government", "Private", "Internship", "Apprenticeship"];

export default function Page() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [jobType, setJobType] = useState("All");
  const [semantic, setSemantic] = useState(false);
  const [location, setLocation] = useState("");
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [total, setTotal] = useState<number | null>(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      if (semantic) {
        if (!q.trim()) {
          setError("Type a phrase to search by meaning, e.g. \"remote data analyst role\".");
          setJobs([]);
          setTotal(null);
          return;
        }
        const r = await fetch(`${API}/search/semantic?q=${encodeURIComponent(q)}`);
        if (!r.ok) throw new Error("Could not run semantic search right now.");
        const results = await r.json();
        setJobs(results.map((item: any) => item.job));
        setTotal(results.length);
        return;
      }

      const params = new URLSearchParams();
      if (q) params.set("search", q);
      if (jobType !== "All") params.set("job_type", jobType);
      if (location) params.set("location", location);
      if (verifiedOnly) params.set("verified", "true");
      params.set("limit", "20"); params.set("offset", String(offset));

      const r = await fetch(`${API}/jobs?${params.toString()}`);
      if (!r.ok) throw new Error("Could not load opportunities right now.");
      setJobs(await r.json());
      const totalHeader = r.headers.get("X-Total-Count");
      setTotal(totalHeader ? parseInt(totalHeader, 10) : null);
    } catch (e: any) {
      setError(e.message || "Something went wrong.");
      setJobs([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobType, offset]);

  async function save(id: number) {
    try {
      await api(`/saved-jobs/${id}`, { method: "POST" });
      alert("Saved");
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function apply(id: number) {
    try {
      await api(`/jobs/${id}/apply`, { method: "POST", body: JSON.stringify({}) });
      alert("Application submitted");
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <main className="container page">
      <div className="pagehead">
        <div>
          <span className="eyebrow">Opportunity engine</span>
          <h1>Jobs, internships &amp; apprenticeships</h1>
          <p className="muted" style={{ fontSize: 13 }}><a href="/career-copilot">Ask the Career Copilot which jobs suit you →</a></p>
        </div>
        <div className="search">
          <input
            className="field"
            placeholder={semantic ? "Describe the role you want…" : "Search title, organization, skills..."}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
          />
          <button className="btn" onClick={load}>
            Search
          </button>
          <button
            className={`chip ${semantic ? "chip-active" : ""}`}
            onClick={() => setSemantic((v) => !v)}
            title="Search by meaning instead of exact keywords"
          >
            {semantic ? "Semantic: on" : "Semantic: off"}
          </button>
        </div>
      </div>

      {!semantic && (
        <>
        <div className="filters">
          {JOB_TYPES.map((t) => (
            <button
              key={t}
              className={`chip ${jobType === t ? "chip-active" : ""}`}
              onClick={() => setJobType(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="filters"><input className="field" style={{maxWidth:260}} placeholder="Location" value={location} onChange={e=>setLocation(e.target.value)}/><label className="checkbox-label"><input type="checkbox" checked={verifiedOnly} onChange={e=>setVerifiedOnly(e.target.checked)}/> Verified only</label><button className="btn secondary" onClick={()=>{setOffset(0);load()}}>Apply filters</button></div>
        </>
      )}

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Loading opportunities…</p>}
      {!loading && total !== null && <p className="muted">{total} opportunities found</p>}

      <div className="jobs">
        {jobs.map((j) => (
          <article className="card" key={j.id}>
            <div className="row">
              <span className="pill">{j.job_type}</span>
              {j.employment_type && <span className="pill">{j.employment_type}</span>}
              {j.work_mode && <span className="pill">{j.work_mode}</span>}
              {j.verified && <span className="verified">Verified</span>}
            </div>
            <h2><a href={`/jobs/${j.id}`}>{j.title}</a></h2>
            <p className="strong">{j.organization}</p>
            <p>
              {j.location}
              {j.vacancies ? ` • ${j.vacancies} vacancies` : ""}
            </p>
            <p className="muted">{j.qualification}</p>
            {(j.stipend || j.salary) && (
              <p>
                {j.job_type === "Internship" || j.job_type === "Apprenticeship" ? "Stipend" : "Salary"}:{" "}
                <b>{j.stipend || j.salary}</b>
                {j.duration ? ` • ${j.duration}` : ""}
              </p>
            )}
            {j.deadline && (
              <p>
                Deadline: <b>{j.deadline}</b>
              </p>
            )}
            {j.admit_card_date && (
              <p>
                Admit card: <b>{j.admit_card_date}</b>
                {j.admit_card_url && (
                  <>
                    {" "}
                    —{" "}
                    <a href={safeHref(j.admit_card_url)} target="_blank" rel="noreferrer">
                      Download
                    </a>
                  </>
                )}
              </p>
            )}
            {j.result_date && (
              <p>
                Result: <b>{j.result_date}</b>
                {j.result_url && (
                  <>
                    {" "}
                    —{" "}
                    <a href={safeHref(j.result_url)} target="_blank" rel="noreferrer">
                      View
                    </a>
                  </>
                )}
              </p>
            )}
            <div className="actions">
              <a className="btn secondary" href={`/jobs/${j.id}`}>View details</a>
              <button className="btn secondary" onClick={() => save(j.id)}>
                Save
              </button>
              <a className="btn secondary" href={`/career-ai?job=${j.id}`}>Career AI</a>
              <a className="btn secondary" href={`/resume?job=${j.id}`}>Resume match</a>
              {j.owner_user_id && (
                <button className="btn" onClick={() => apply(j.id)}>
                  Apply now
                </button>
              )}
              {j.apply_url && (
                <a className="btn" href={safeHref(j.apply_url)} target="_blank" rel="noreferrer">
                  Official apply
                </a>
              )}
            </div>
          </article>
        ))}
      </div>

      {!loading && !jobs.length && !error && <div className="empty">No published opportunities found.</div>}
      {!semantic && total!==null && total>20 && <div className="actions" style={{justifyContent:"center",marginTop:28}}><button className="btn secondary" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-20))}>Previous</button><span className="muted">{offset+1}–{Math.min(offset+20,total)} of {total}</span><button className="btn secondary" disabled={offset+20>=total} onClick={()=>setOffset(offset+20)}>Next</button></div>}
    </main>
  );
}
