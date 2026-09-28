"use client";
/**
 * V25.2 — platform analytics.
 *
 * Aggregates only. Nothing on this screen identifies a candidate, and
 * the API provides no demographic breakdown to render — CareerOS
 * stores no protected characteristics and deliberately builds no
 * proxy for them.
 */
import { useEffect, useState } from "react";
import { AdminShell, AsyncState } from "@/components/admin/AdminShell";
import { adminApi, formatDate } from "@/lib/adminApi";

type Series = { date: string; count: number }[];
type Bucket = { key: string; count: number }[];

function Sparkline({ data, label }: { data: Series; label: string }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((sum, d) => sum + d.count, 0);
  return (
    <div className="card">
      <b>{label}</b>
      <p className="muted">{total.toLocaleString()} in this period</p>
      {/* A plain bar row rather than a charting dependency: the
          project ships no chart library, and adding one for this
          screen alone would be a poor trade. */}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 80, marginTop: 10 }}>
        {data.map((point) => (
          <div
            key={point.date}
            title={`${point.date}: ${point.count}`}
            aria-label={`${point.date}: ${point.count}`}
            style={{
              flex: 1,
              minWidth: 2,
              height: `${Math.round((point.count / max) * 100)}%`,
              background: "var(--blue)",
              opacity: point.count ? 1 : 0.15,
              borderRadius: 2,
            }}
          />
        ))}
      </div>
    </div>
  );
}

function Buckets({ heading, data }: { heading: string; data: Bucket }) {
  if (!data || data.length === 0) return null;
  return (
    <div className="card">
      <b>{heading}</b>
      <table className="srctable">
        <thead>
          <tr>
            <th scope="col">Value</th>
            <th scope="col">Count</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.key}>
              <td>{String(row.key).replace(/_/g, " ")}</td>
              <td>{row.count.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    adminApi(`/analytics?days=${days}`)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [days]);

  return (
    <AdminShell title="Platform analytics" description="Aggregate platform activity. No individual candidate data.">
      <div className="filters">
        {[7, 30, 90, 365].map((option) => (
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

      <AsyncState loading={loading} error={error} empty={!data} emptyMessage="No analytics available.">
        {data && (
          <>
            <p className="muted">Generated {formatDate(data.generated_at)}</p>

            <section className="section">
              <h2>Users</h2>
              <div className="grid2">
                <Sparkline data={data.users.registrations_over_time} label="Registrations over time" />
                <Buckets heading="By role" data={data.users.by_role} />
                <Buckets heading="By account status" data={data.users.by_account_status} />
                <div className="card">
                  <b>Verification</b>
                  <div className="statgrid">
                    <div className="statcard">
                      <b>{data.users.verified.toLocaleString()}</b>
                      <span>Verified</span>
                    </div>
                    <div className="statcard">
                      <b>{data.users.unverified.toLocaleString()}</b>
                      <span>Unverified</span>
                    </div>
                    <div className="statcard">
                      <b>{data.users.users_with_session_in_period.toLocaleString()}</b>
                      <span>With a session this period</span>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section className="section">
              <h2>Organizations</h2>
              <div className="grid2">
                <Sparkline data={data.organizations.created_over_time} label="Organizations created" />
                <Buckets heading="By verification status" data={data.organizations.by_verification_status} />
                <div className="card">
                  <b>Organizations with active hiring</b>
                  {data.organizations.with_active_hiring.length === 0 ? (
                    <p className="muted">No organization currently has a published listing.</p>
                  ) : (
                    <table className="srctable">
                      <thead>
                        <tr>
                          <th scope="col">Organization</th>
                          <th scope="col">Published jobs</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.organizations.with_active_hiring.map((row: any) => (
                          <tr key={row.organization_id}>
                            <td>{row.name}</td>
                            <td>{row.published_jobs}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            </section>

            <section className="section">
              <h2>Jobs</h2>
              <div className="grid2">
                <Sparkline data={data.jobs.created_over_time} label="Jobs created" />
                <Sparkline data={data.jobs.published_over_time} label="Jobs published" />
                <Buckets heading="By status" data={data.jobs.by_status} />
                <Buckets heading="By moderation reason" data={data.jobs.by_moderation_reason} />
              </div>
            </section>

            <section className="section">
              <h2>Applications</h2>
              <div className="grid2">
                <Sparkline data={data.applications.over_time} label="Applications over time" />
                <Buckets heading="By application status" data={data.applications.by_status} />
                <Buckets heading="By job status" data={data.applications.by_job_status} />
                <div className="card">
                  <b>Highest-volume listings</b>
                  <table className="srctable">
                    <thead>
                      <tr>
                        <th scope="col">Job</th>
                        <th scope="col">Status</th>
                        <th scope="col">Applications</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.applications.top_jobs_by_volume.map((row: any) => (
                        <tr key={row.job_id}>
                          <td>{row.title}</td>
                          <td>{row.status}</td>
                          <td>{row.applications}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <section className="section">
              <h2>Metrics not reported</h2>
              <ul>
                {Object.entries(data.omitted_metrics).map(([key, reason]) => (
                  <li key={key} className="muted">
                    <b>{key.replace(/_/g, " ")}</b> — {String(reason)}
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </AsyncState>
    </AdminShell>
  );
}
