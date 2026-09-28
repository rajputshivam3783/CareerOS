"use client";
import { safeHref } from "@/lib/safe";

// V22.2 — the one card component both KanbanBoard and the list view
// render, so a card looks and behaves identically everywhere (single
// source of truth for "what does an application look like").

import { Application, DeadlineUrgency } from "@/lib/applications";
import StatusBadge from "@/components/applications/StatusBadge";
import StatusChangeControl from "@/components/applications/StatusChangeControl";

function daysUntil(dateStr: string): number {
  const ms = new Date(dateStr + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime();
  return Math.round(ms / 86400000);
}

function urgencyOf(dateStr: string): DeadlineUrgency {
  const d = daysUntil(dateStr);
  if (d < 0) return "overdue";
  if (d <= 3) return "due_soon";
  return "upcoming";
}

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

export default function ApplicationCard({
  application,
  onChanged,
  onError,
  onDelete,
  draggable = false,
  onDragStart,
  onDragEnd,
  compact = false,
}: {
  application: Application;
  onChanged: (updated: Application) => void;
  onError: (message: string) => void;
  onDelete?: (id: number) => void;
  draggable?: boolean;
  onDragStart?: (e: React.DragEvent) => void;
  onDragEnd?: () => void;
  compact?: boolean;
}) {
  const a = application;
  const actionNeeded = a.deadline ? urgencyOf(a.deadline) !== "upcoming" : false;

  return (
    <article
      className={compact ? "kcard" : "card"}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      style={compact ? { cursor: draggable ? "grab" : undefined } : undefined}
      aria-label={`${a.job_title} at ${a.company}, status ${a.status}`}
    >
      <div className="row" style={{ alignItems: "flex-start" }}>
        <div>
          <b>{a.job_title}</b>
          <p className="muted" style={{ margin: "2px 0", fontSize: 13 }}>
            {a.company}
            {a.location ? ` · ${a.location}` : ""}
          </p>
        </div>
        {!compact && <StatusBadge status={a.status} />}
      </div>

      <p className="muted" style={{ fontSize: 12, margin: "6px 0" }}>
        {a.source ? a.source : "CareerOS"}
        {a.applied_at ? ` · Applied ${a.applied_at}` : ""}
      </p>

      {a.deadline && (
        <span className={`pill ${URGENCY_CLASS[urgencyOf(a.deadline)]}`} style={{ fontSize: 11 }}>
          {actionNeeded && "⚠ "}
          {URGENCY_LABEL[urgencyOf(a.deadline)]}: {a.deadline}
        </span>
      )}

      <div className="actions" style={{ marginTop: 10, flexWrap: "wrap" }}>
        <a className="linkbtn" href={`/applications/${a.id}`}>
          View
        </a>
        {a.job_id ? (
          <a className="linkbtn" href={`/jobs/${a.job_id}`}>
            View Job
          </a>
        ) : (
          a.job_url && (
            <a className="linkbtn" href={safeHref(a.job_url)} target="_blank" rel="noreferrer">
              External listing ↗
            </a>
          )
        )}
        <StatusChangeControl application={a} onChanged={onChanged} onError={onError} />
        {onDelete && (
          <button type="button" className="linkbtn danger" onClick={() => onDelete(a.id)}>
            Delete
          </button>
        )}
      </div>
    </article>
  );
}
