// V22.2 — top statistics. Real backend data only (ApplicationDashboard
// comes straight from GET /applications/dashboard) — never fake/demo
// numbers, per the spec.

import { ApplicationDashboard } from "@/lib/applications";

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="statcard">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

function ratePct(rate: number | null): string {
  return rate === null ? "Not enough data yet" : `${Math.round(rate * 100)}%`;
}

export default function DashboardStats({ dashboard }: { dashboard: ApplicationDashboard }) {
  const s = dashboard.by_status;
  return (
    <>
      <div className="statgrid">
        <Stat label="Total Applications" value={dashboard.total} />
        <Stat label="Planning to Apply" value={s.PLANNING_TO_APPLY} />
        <Stat label="Applied" value={s.APPLIED} />
        <Stat label="Assessments" value={s.ASSESSMENT} />
        <Stat label="Interviews" value={s.INTERVIEW} />
        <Stat label="Offers" value={s.OFFER} />
        <Stat label="Accepted" value={s.ACCEPTED} />
        <Stat label="Rejected" value={s.REJECTED} />
      </div>

      <div className="row" style={{ marginTop: 14, flexWrap: "wrap", gap: 24 }}>
        <p className="muted" style={{ fontSize: 13 }}>
          <b>{dashboard.applications_this_week}</b> this week · <b>{dashboard.applications_this_month}</b> this month
        </p>
        <p className="muted" style={{ fontSize: 13 }}>
          Applied → Interview: <b>{ratePct(dashboard.conversion_rates.applied_to_interview)}</b> · Interview → Offer:{" "}
          <b>{ratePct(dashboard.conversion_rates.interview_to_offer)}</b> · Offer → Accepted:{" "}
          <b>{ratePct(dashboard.conversion_rates.offer_to_acceptance)}</b>
        </p>
      </div>
    </>
  );
}
