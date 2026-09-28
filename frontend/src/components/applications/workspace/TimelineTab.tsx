"use client";

import { useEffect, useState } from "react";
import { SkeletonLines } from "@/components/Skeleton";
import { TimelineEntry, fetchTimeline } from "@/lib/applicationWorkspace";

const EVENT_ICONS: Record<string, string> = {
  APPLICATION_CREATED: "🆕",
  STATUS_CHANGED: "🔄",
  NOTE_ADDED: "📝",
  INTERVIEW_SCHEDULED: "📅",
  INTERVIEW_COMPLETED: "✅",
  TASK_CREATED: "☑️",
  TASK_COMPLETED: "✔️",
  DOCUMENT_UPLOADED: "📎",
};

export default function TimelineTab({ applicationId }: { applicationId: number }) {
  const [entries, setEntries] = useState<TimelineEntry[] | null>(null);
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [error, setError] = useState("");

  useEffect(() => {
    setEntries(null);
    fetchTimeline(applicationId, order)
      .then(setEntries)
      .catch((e) => setError(e.message || "Could not load the timeline."));
  }, [applicationId, order]);

  return (
    <div>
      {error && <p className="error">{error}</p>}
      <div className="row" style={{ marginBottom: 10 }}>
        <span className="muted" style={{ fontSize: 13 }}>
          {entries ? `${entries.length} event${entries.length === 1 ? "" : "s"}` : ""}
        </span>
        <div className="viewtoggle">
          <button className={order === "desc" ? "active" : ""} onClick={() => setOrder("desc")}>
            Newest first
          </button>
          <button className={order === "asc" ? "active" : ""} onClick={() => setOrder("asc")}>
            Oldest first
          </button>
        </div>
      </div>

      {entries === null ? (
        <SkeletonLines count={5} />
      ) : entries.length === 0 ? (
        <div className="emptystate">
          <b>No activity yet</b>
          Status changes, notes, interviews, tasks, and document uploads will appear here.
        </div>
      ) : (
        <div className="tl-list">
          {entries.map((e, i) => (
            <div key={`${e.source}-${e.source_id}-${i}`} className="tl-item">
              <span className="tl-dot" aria-hidden="true" />
              <b>
                {EVENT_ICONS[e.event_type] || "•"} {e.title}
              </b>
              {e.description && <p style={{ margin: "2px 0" }}>{e.description}</p>}
              <p className="muted">{new Date(e.occurred_at).toLocaleString()}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
