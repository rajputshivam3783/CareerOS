"use client";

// V22.2 — Kanban board. Presentational: the parent page owns fetching
// (single source of truth, avoids duplicate/competing fetches between
// Kanban and List views) and passes the current, already-filtered set
// of applications in. Drag-and-drop follows the exact same pattern as
// the existing recruiter pipeline board
// (src/app/recruiter/jobs/[id]/pipeline/page.tsx): optimistic move,
// roll back to server state on failure, backend is the source of
// truth for the actual status (STATUS CHANGE requirement: "Backend
// remains the source of truth").

import { useState } from "react";
import ApplicationCard from "@/components/applications/ApplicationCard";
import {
  Application,
  ApplicationStatus,
  KANBAN_STATUSES,
  REOPEN_REQUIRED_STATUSES,
  STATUS_LABELS,
  changeApplicationStatus,
} from "@/lib/applications";

export default function KanbanBoard({
  items,
  onItemsChange,
  onError,
  onDelete,
}: {
  items: Application[];
  onItemsChange: (items: Application[]) => void;
  onError: (message: string) => void;
  onDelete: (id: number) => void;
}) {
  const [dragOverStatus, setDragOverStatus] = useState<ApplicationStatus | null>(null);
  const [draggingId, setDraggingId] = useState<number | null>(null);

  const columns: Record<string, Application[]> = {};
  for (const status of KANBAN_STATUSES) columns[status] = [];
  for (const a of items) {
    if (columns[a.status]) columns[a.status].push(a);
  }

  async function moveCard(applicationId: number, toStatus: ApplicationStatus) {
    const current = items.find((a) => a.id === applicationId);
    if (!current || current.status === toStatus) return;

    const needsReopen = REOPEN_REQUIRED_STATUSES.includes(current.status);
    if (needsReopen) {
      const ok = confirm(
        `"${STATUS_LABELS[current.status]}" is a closed status. Reopen this application and move it to "${STATUS_LABELS[toStatus]}"?`
      );
      if (!ok) return;
    }

    const previous = items;
    // Optimistic move so the board feels instant (PERFORMANCE: avoid
    // waiting on the network for the UI to respond) — rolled back
    // below if the backend rejects the change.
    onItemsChange(items.map((a) => (a.id === applicationId ? { ...a, status: toStatus } : a)));

    try {
      const updated = await changeApplicationStatus(applicationId, toStatus, { reopen: needsReopen });
      onItemsChange(previous.map((a) => (a.id === applicationId ? updated : a)));
    } catch (e: any) {
      onItemsChange(previous); // restore previous UI state on failure
      onError(e.message || "Could not move this application — it stayed in its previous column.");
    }
  }

  return (
    <div className="board" role="list" aria-label="Applications by status">
      {KANBAN_STATUSES.map((status) => {
        const cards = columns[status];
        return (
          <div
            key={status}
            role="listitem"
            className={`col ${dragOverStatus === status ? "dragover" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOverStatus(status);
            }}
            onDragLeave={() => setDragOverStatus((s) => (s === status ? null : s))}
            onDrop={(e) => {
              e.preventDefault();
              setDragOverStatus(null);
              const id = Number(e.dataTransfer.getData("text/plain"));
              if (id && draggingId !== null) moveCard(id, status);
              setDraggingId(null);
            }}
          >
            <h3>
              {STATUS_LABELS[status]} <span>{cards.length}</span>
            </h3>
            {cards.map((a) => (
              <ApplicationCard
                key={a.id}
                application={a}
                compact
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData("text/plain", String(a.id));
                  setDraggingId(a.id);
                }}
                onDragEnd={() => setDraggingId(null)}
                onChanged={(updated) => onItemsChange(items.map((x) => (x.id === updated.id ? updated : x)))}
                onError={onError}
                onDelete={onDelete}
              />
            ))}
            {!cards.length && <p className="kempty">Drop here, or use "Change Status" on a card.</p>}
          </div>
        );
      })}
    </div>
  );
}
