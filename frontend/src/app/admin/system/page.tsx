"use client";
/**
 * V25.2 — system health, background jobs and ingestion monitoring.
 *
 * An indicator reported as "unknown" means CareerOS has no way to
 * check it in this deployment (no provider configured, feature
 * disabled, scheduler running elsewhere). It is rendered as its own
 * distinct state rather than being collapsed into "ok" or "error",
 * because a fabricated green light is worse than an honest gap.
 */
import { useCallback, useEffect, useState } from "react";
import { AdminShell, AsyncState } from "@/components/admin/AdminShell";
import { adminApi, formatDate, statusBadgeClass } from "@/lib/adminApi";

function badge(status: string) {
  if (status === "unknown") return "badge badge-disabled";
  return statusBadgeClass(status);
}

export default function SystemPage() {
  const [health, setHealth] = useState<any | null>(null);
  const [jobs, setJobs] = useState<any | null>(null);
  const [ingestion, setIngestion] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [h, j, i] = await Promise.all([
        adminApi("/system/health"),
        adminApi("/system/background-jobs"),
        adminApi("/system/ingestion"),
      ]);
      setHealth(h);
      setJobs(j);
      setIngestion(i);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <AdminShell title="System health" description="Live platform indicators. No credentials are shown here.">
      <div className="actions">
        <button className="btn secondary" type="button" onClick={load}>
          Refresh
        </button>
      </div>

      <AsyncState loading={loading} error={error} empty={!health} emptyMessage="No health data available.">
        {health && (
          <>
            <section className="section">
              <div className="row">
                <h2>Overall</h2>
                <span className={badge(health.status)}>{health.status}</span>
              </div>
              <p className="muted">Checked {formatDate(health.checked_at)}</p>
              <table className="srctable">
                <caption className="muted">Platform indicators</caption>
                <thead>
                  <tr>
                    <th scope="col">Indicator</th>
                    <th scope="col">Status</th>
                    <th scope="col">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {health.indicators.map((indicator: any) => (
                    <tr key={indicator.name}>
                      <td>{indicator.name.replace(/_/g, " ")}</td>
                      <td>
                        <span className={badge(indicator.status)}>{indicator.status}</span>
                      </td>
                      <td>{indicator.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            {jobs && (
              <section className="section">
                <h2>Background jobs</h2>
                {jobs.queues.map((queue: any) => (
                  <div className="card" key={queue.name}>
                    <b>{queue.name}</b>
                    <p className="muted">{queue.description}</p>
                    <div className="statgrid">
                      <div className="statcard">
                        <b>{queue.queued}</b>
                        <span>Queued</span>
                      </div>
                      <div className="statcard">
                        <b>{queue.retrying}</b>
                        <span>Retrying</span>
                      </div>
                      <div className="statcard">
                        <b>{queue.failed}</b>
                        <span>Failed</span>
                      </div>
                      <div className="statcard">
                        <b>{queue.sent}</b>
                        <span>Sent</span>
                      </div>
                    </div>
                    <p className="muted">
                      Last success {formatDate(queue.last_success_at)} · last failure{" "}
                      {formatDate(queue.last_failure_at)}
                    </p>
                  </div>
                ))}
                <div className="card">
                  <b>Scheduled jobs</b>
                  <p className="muted">{jobs.scheduler.detail}</p>
                  {(jobs.scheduler.jobs || []).length > 0 && (
                    <table className="srctable">
                      <thead>
                        <tr>
                          <th scope="col">Job</th>
                          <th scope="col">Last run</th>
                          <th scope="col">Outcome</th>
                        </tr>
                      </thead>
                      <tbody>
                        {jobs.scheduler.jobs.map((job: any) => (
                          <tr key={job.job_id}>
                            <td>{job.job_id}</td>
                            <td>{formatDate(job.last_run_at)}</td>
                            <td>
                              <span className={badge(job.ok ? "ok" : "error")}>
                                {job.ok ? "succeeded" : "failed"}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </section>
            )}

            {ingestion && (
              <section className="section">
                <h2>Ingestion sources</h2>
                {ingestion.note && <p className="muted">{ingestion.note}</p>}
                {ingestion.sources.length === 0 ? (
                  <p className="empty">No ingestion sources are registered.</p>
                ) : (
                  <table className="srctable">
                    <caption className="muted">Configured ingestion sources</caption>
                    <thead>
                      <tr>
                        <th scope="col">Source</th>
                        <th scope="col">Collecting now</th>
                        <th scope="col">Registry status</th>
                        <th scope="col">Last success</th>
                        <th scope="col">Last failure</th>
                        <th scope="col">Imported</th>
                        <th scope="col">Skipped</th>
                        <th scope="col">Unresolved failures</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ingestion.sources.map((source: any) => (
                        <tr key={source.source_name}>
                          <td>{source.source_name}</td>
                          <td>
                            <span className={badge(source.currently_collecting ? "ok" : "unknown")}>
                              {source.currently_collecting ? "yes" : "no"}
                            </span>
                          </td>
                          <td>{source.registry_status}</td>
                          <td>{formatDate(source.last_success_at)}</td>
                          <td>{formatDate(source.last_failure_at)}</td>
                          <td>{source.jobs_imported}</td>
                          <td>{source.records_skipped}</td>
                          <td>{source.unresolved_dead_letters}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
            )}
          </>
        )}
      </AsyncState>
    </AdminShell>
  );
}
