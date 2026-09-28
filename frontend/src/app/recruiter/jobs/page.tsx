"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const FILTERS = ["all", "draft", "review", "published", "closed", "archived", "rejected"];

export default function Page() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [filter, setFilter] = useState("all");
  const [err, setErr] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  async function load() {
    try {
      setJobs(await api("/recruiter/jobs"));
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function act(jobId: number, action: string) {
    if (action === "delete" && !window.confirm("Delete this job permanently? This cannot be undone.")) return;
    setErr("");
    setBusyId(jobId);
    try {
      if (action === "delete") {
        await api(`/recruiter/jobs/${jobId}`, { method: "DELETE" });
      } else {
        await api(`/recruiter/jobs/${jobId}/${action}`, { method: "POST" });
      }
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusyId(null);
    }
  }

  const visible = filter === "all" ? jobs : jobs.filter((j) => j.status === filter);

  return (
    <main className="container page">
      <span className="eyebrow">Job management</span>
      <div className="pagehead">
        <div>
          <h1>Your job listings</h1>
          <p className="muted">Draft, submit, publish, close, reopen, archive or clone any job you own.</p>
        </div>
        <a className="btn" href="/recruiter/jobs/new">
          + Create job
        </a>
      </div>

      {err && <p className="error">{err}</p>}

      <div className="filters">
        {FILTERS.map((f) => (
          <button key={f} className={`chip ${filter === f ? "chip-active" : ""}`} onClick={() => setFilter(f)}>
            {f === "all" ? "All" : f[0].toUpperCase() + f.slice(1)}
            {f !== "all" && ` (${jobs.filter((j) => j.status === f).length})`}
          </button>
        ))}
      </div>

      <div className="jobs">
        {visible.map((j) => (
          <div className="card" key={j.id}>
            <div className="row">
              <span className={`pill status-${j.status}`}>{j.status}</span>
              <span className="pill">{j.job_type}</span>
            </div>
            <h2>{j.title}</h2>
            <p className="strong">{j.organization}</p>
            <p className="muted">
              {j.location} · {j.work_mode || ""}
            </p>

            <div className="jobcard-actions">
              <a className="linkbtn" href={`/recruiter/jobs/${j.id}/edit`}>
                Edit
              </a>
              {j.status === "published" && (
                <a className="linkbtn" href={`/recruiter/jobs/${j.id}/pipeline`}>
                  Pipeline
                </a>
              )}
              {j.status === "published" && (
                <a className="linkbtn" href={`/recruiter/candidates?job_id=${j.id}`}>
                  Find candidates
                </a>
              )}
              {j.status === "draft" && (
                <button className="linkbtn" disabled={busyId === j.id} onClick={() => act(j.id, "submit-for-review")}>
                  Submit for review
                </button>
              )}
              {j.status === "published" && (
                <button className="linkbtn" disabled={busyId === j.id} onClick={() => act(j.id, "close")}>
                  Close
                </button>
              )}
              {j.status === "closed" && (
                <button className="linkbtn" disabled={busyId === j.id} onClick={() => act(j.id, "reopen")}>
                  Reopen
                </button>
              )}
              <button className="linkbtn" disabled={busyId === j.id} onClick={() => act(j.id, "clone")}>
                Clone
              </button>
              {j.status !== "archived" && (
                <button className="linkbtn" disabled={busyId === j.id} onClick={() => act(j.id, "archive")}>
                  Archive
                </button>
              )}
              <button className="linkbtn danger" disabled={busyId === j.id} onClick={() => act(j.id, "delete")}>
                Delete
              </button>
            </div>
          </div>
        ))}
        {!visible.length && <p className="empty">No jobs in this view yet.</p>}
      </div>
    </main>
  );
}
