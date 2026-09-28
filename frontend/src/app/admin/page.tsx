"use client";
/**
 * V25.2 — the platform administration dashboard.
 *
 * Every figure rendered here comes from GET /admin/dashboard, which
 * returns live COUNTs (see app/services/platform_analytics.py). No
 * metric is estimated or hardcoded, and the API's `omitted_metrics`
 * map — its record of which suggested metrics have no supporting data
 * — is surfaced rather than hidden, so a missing number is an answered
 * question rather than an apparent gap.
 *
 * The job review queue and recruiter approvals that this page carried
 * before V25.2 now live on /admin/jobs, next to the rest of the
 * moderation tooling.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { AdminShell, AsyncState } from "@/components/admin/AdminShell";
import { adminApi, formatDate, statusBadgeClass } from "@/lib/adminApi";

type Dashboard = {
  generated_at: string;
  users: Record<string, number>;
  organizations: Record<string, number>;
  jobs: Record<string, number>;
  applications: Record<string, number>;
  recent_activity: any[];
  omitted_metrics: Record<string, string>;
};

const LABELS: Record<string, string> = {
  total: "Total",
  active: "Active",
  suspended: "Suspended",
  verified: "Verified",
  candidates: "Active candidates",
  recruiters: "Active recruiters",
  recruiters_pending_approval: "Recruiters pending approval",
  platform_admins: "Platform administrators",
  new_last_30_days: "New in last 30 days",
  pending_verification: "Pending verification",
  pending_invitations: "Pending invitations",
  published: "Published",
  pending_review: "Pending review",
  rejected: "Rejected",
  closed: "Closed",
  published_past_deadline: "Published, past deadline",
  hired: "Hired",
};

function Section({ heading, data, link }: { heading: string; data: Record<string, number>; link?: string }) {
  return (
    <section className="section">
      <div className="row">
        <h2>{heading}</h2>
        {link && (
          <Link className="linkbtn" href={link}>
            Manage →
          </Link>
        )}
      </div>
      <div className="statgrid">
        {Object.entries(data).map(([key, value]) => (
          <div className="statcard" key={key}>
            <b>{value.toLocaleString()}</b>
            <span>{LABELS[key] || key.replace(/_/g, " ")}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Page() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminApi<Dashboard>("/dashboard")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <AdminShell
      title="Platform dashboard"
      description="Live platform metrics and recent administrative activity."
    >
      <AsyncState loading={loading} error={error} empty={!data} emptyMessage="No dashboard data available.">
        {data && (
          <>
            <p className="muted">Generated {formatDate(data.generated_at)}</p>
            <Section heading="Users" data={data.users} link="/admin/users" />
            <Section heading="Organizations" data={data.organizations} link="/admin/organizations" />
            <Section heading="Jobs" data={data.jobs} link="/admin/jobs" />
            <Section heading="Applications" data={data.applications} />

            <section className="section">
              <div className="row">
                <h2>Recent administrative activity</h2>
                <Link className="linkbtn" href="/admin/audit">
                  Full audit log →
                </Link>
              </div>
              {data.recent_activity.length === 0 ? (
                <p className="empty">No platform administrator actions have been recorded yet.</p>
              ) : (
                <table className="srctable">
                  <thead>
                    <tr>
                      <th scope="col">When</th>
                      <th scope="col">Action</th>
                      <th scope="col">Target</th>
                      <th scope="col">Administrator</th>
                      <th scope="col">Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_activity.map((row) => (
                      <tr key={row.id}>
                        <td>{formatDate(row.created_at)}</td>
                        <td>{row.action}</td>
                        <td>
                          {row.target_type}
                          {row.target_id ? ` #${row.target_id}` : ""}
                        </td>
                        <td>{row.actor_label || "—"}</td>
                        <td>
                          <span className={statusBadgeClass(row.result)}>{row.result}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section className="section">
              <h2>Metrics not reported</h2>
              <p className="muted">
                These were considered and deliberately not shown, because the underlying data does not
                exist. Showing an approximation would be worse than showing nothing.
              </p>
              <ul>
                {Object.entries(data.omitted_metrics).map(([key, reason]) => (
                  <li key={key} className="muted">
                    <b>{key.replace(/_/g, " ")}</b> — {reason}
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
