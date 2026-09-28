// V22.2 — "Application Activity" dashboard section. Reuses the same
// recent_activity data ApplicationStats/ApplicationDashboard already
// return (built from ApplicationStatusHistory) — no separate activity
// system, per the spec ("do not create a separate duplicate activity
// system unless absolutely necessary").

import { STATUS_LABELS } from "@/lib/applications";
import { ApplicationDashboard } from "@/lib/applications";

function describe(entry: ApplicationDashboard["recent_activity"][number]): string {
  if (!entry.old_status) return `Application added — ${STATUS_LABELS[entry.new_status]}`;
  return `${STATUS_LABELS[entry.old_status]} → ${STATUS_LABELS[entry.new_status]}`;
}

export default function RecentActivity({ items }: { items: ApplicationDashboard["recent_activity"] }) {
  return (
    <div className="card">
      <h2>Recent Activity</h2>
      {items.length === 0 ? (
        <p className="muted">No activity yet — add an application to get started.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((entry, i) => (
            <div key={i} style={{ borderLeft: "3px solid var(--line)", paddingLeft: 10 }}>
              <p style={{ margin: 0, fontSize: 13 }}>
                <b>{entry.company}</b> — {entry.job_title}: {describe(entry)}
              </p>
              <p className="muted" style={{ fontSize: 12, margin: 0 }}>
                {new Date(entry.changed_at).toLocaleString()}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
