"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { formatApiError } from "@/lib/api";
import {
  JobAlert,
  JobAlertMatch,
  JobAlertRun,
  getJobAlert,
  getJobAlertHistory,
  getJobAlertMatches,
  runJobAlertNow,
} from "@/lib/jobAlerts";

export default function JobAlertDetailPage() {
  const params = useParams();
  const id = Number(params.id);

  const [alert, setAlert] = useState<JobAlert | null>(null);
  const [matches, setMatches] = useState<JobAlertMatch[] | null>(null);
  const [history, setHistory] = useState<JobAlertRun[] | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<JobAlertRun | null>(null);

  async function load() {
    setError("");
    try {
      const [a, m, h] = await Promise.all([getJobAlert(id), getJobAlertMatches(id), getJobAlertHistory(id)]);
      setAlert(a);
      setMatches(m.items);
      setHistory(h.items);
    } catch (e) {
      setError(formatApiError(e, "Couldn't load this alert"));
    }
  }

  useEffect(() => {
    if (id) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function handleRunNow() {
    setRunning(true);
    setError("");
    try {
      const result = await runJobAlertNow(id);
      setRunResult(result);
      await load();
    } catch (e) {
      setError(formatApiError(e, "Couldn't run this alert"));
    } finally {
      setRunning(false);
    }
  }

  if (error && !alert) {
    return (
      <div className="page container">
        <div className="error">{error}</div>
        <Link href="/job-alerts" className="linkbtn">Back to Job Alerts</Link>
      </div>
    );
  }

  if (!alert) return <div className="page container"><p className="loading">Loading…</p></div>;

  return (
    <div className="page container">
      <div className="breadcrumbs">
        <Link href="/job-alerts">Job Alerts</Link>
        <span className="sep">/</span>
        <span>{alert.name}</span>
      </div>

      <div className="pagehead">
        <div>
          <p className="eyebrow">{alert.frequency} · {alert.enabled ? "Active" : "Disabled"}</p>
          <h1>{alert.name}</h1>
        </div>
        <button className="btn" onClick={handleRunNow} disabled={running}>{running ? "Running…" : "Run now"}</button>
      </div>

      {error && <div className="error">{error}</div>}
      {runResult && (
        <p className="muted">
          Last run: {runResult.jobs_matched} match(es), {runResult.notifications_created} notification(s), {runResult.emails_queued} email(s) queued.
        </p>
      )}

      <div className="section">
        <h2>Current matches</h2>
        {matches && matches.length === 0 && <p className="muted">No jobs currently match this alert's criteria.</p>}
        {matches && matches.length > 0 && (
          <div className="qlist">
            {matches.map((m) => (
              <div key={m.job_id} className="qitem">
                <div>
                  <b>{m.title}</b> — {m.organization}{m.location ? ` · ${m.location}` : ""}
                  <div className="muted" style={{ fontSize: 12 }}>{m.match_reasons.join(" · ")}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <span className="pill">{m.relevance_score}</span>
                  {m.already_delivered && <div className="muted" style={{ fontSize: 11 }}>Already notified</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="section">
        <h2>Run history</h2>
        {history && history.length === 0 && <p className="muted">This alert hasn't run yet.</p>}
        {history && history.length > 0 && (
          <table className="srctable">
            <thead>
              <tr>
                <th>Started</th>
                <th>Status</th>
                <th>Scanned</th>
                <th>Matched</th>
                <th>Notifications</th>
                <th>Emails</th>
              </tr>
            </thead>
            <tbody>
              {history.map((r) => (
                <tr key={r.id}>
                  <td>{new Date(r.started_at).toLocaleString()}</td>
                  <td>
                    <span className={`badge badge-${r.status === "SUCCESS" ? "success" : r.status === "FAILED" ? "negative" : "progress"}`}>{r.status}</span>
                    {r.status === "FAILED" && r.error_summary && (
                      <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{r.error_summary}</div>
                    )}
                  </td>
                  <td>{r.candidates_scanned}</td>
                  <td>{r.jobs_matched}</td>
                  <td>{r.notifications_created}</td>
                  <td>{r.emails_queued}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
