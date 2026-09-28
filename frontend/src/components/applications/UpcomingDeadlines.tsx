// V22.2 — "Upcoming Deadlines" dashboard section. Nearest deadline
// first (already sorted server-side); urgency labels come straight
// from the backend (app.applications.service._deadline_urgency) so
// the thresholds are defined in exactly one place.

import { DeadlineUrgency, UpcomingDeadline } from "@/lib/applications";

const URGENCY_CLASS: Record<DeadlineUrgency, string> = {
  overdue: "rec-badge-deadline",
  due_soon: "rec-badge-skillbuild",
  upcoming: "rec-badge-recent",
};

const URGENCY_LABEL: Record<DeadlineUrgency, string> = {
  overdue: "Overdue",
  due_soon: "Due soon",
  upcoming: "Upcoming",
};

export default function UpcomingDeadlines({ items }: { items: UpcomingDeadline[] }) {
  return (
    <div className="card">
      <h2>Upcoming Deadlines</h2>
      {items.length === 0 ? (
        <p className="muted">No upcoming deadlines.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {items.map((d) => (
            <a key={d.application_id} href={`/applications/${d.application_id}`} className="row" style={{ alignItems: "center" }}>
              <span>
                <b>{d.job_title}</b> <span className="muted">· {d.company}</span>
              </span>
              <span className={`pill ${URGENCY_CLASS[d.urgency]}`} style={{ fontSize: 11 }}>
                {URGENCY_LABEL[d.urgency]}: {d.deadline}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
