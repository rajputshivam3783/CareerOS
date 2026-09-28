import { ApplicationStatus, STATUS_LABELS } from "@/lib/applications";

const STATUS_BADGE_CLASS: Record<ApplicationStatus, string> = {
  SAVED: "badge-disabled",
  PLANNING_TO_APPLY: "badge-paused",
  APPLIED: "badge-progress",
  ASSESSMENT: "badge-progress",
  INTERVIEW: "badge-progress",
  OFFER: "badge-success",
  ACCEPTED: "badge-success",
  REJECTED: "badge-negative",
  WITHDRAWN: "badge-negative",
  GHOSTED: "badge-negative",
};

export default function StatusBadge({ status }: { status: ApplicationStatus }) {
  return <span className={`badge ${STATUS_BADGE_CLASS[status] ?? "badge-disabled"}`}>{STATUS_LABELS[status] ?? status}</span>;
}
