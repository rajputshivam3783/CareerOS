"use client";

// V22.2 — ACCESSIBILITY: "drag/drop does not become the only way to
// change status... provide a 'Change Status' action for keyboard/
// mobile users." Used both as a card quick-action (Kanban and List
// views) and standalone. Handles the terminal-status reopen
// confirmation itself so every call site gets that behavior for free.

import { useState } from "react";
import {
  Application,
  ApplicationStatus,
  REOPEN_REQUIRED_STATUSES,
  STATUS_LABELS,
  STATUS_VALUES,
  changeApplicationStatus,
} from "@/lib/applications";

export default function StatusChangeControl({
  application,
  onChanged,
  onError,
}: {
  application: Application;
  onChanged: (updated: Application) => void;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function apply(next: ApplicationStatus) {
    if (next === application.status) {
      setOpen(false);
      return;
    }
    const needsReopen = REOPEN_REQUIRED_STATUSES.includes(application.status);
    if (needsReopen) {
      const ok = confirm(
        `"${STATUS_LABELS[application.status]}" is a closed status. Reopen this application and move it to "${STATUS_LABELS[next]}"?`
      );
      if (!ok) return;
    }
    setBusy(true);
    try {
      const updated = await changeApplicationStatus(application.id, next, { reopen: needsReopen });
      onChanged(updated);
      setOpen(false);
    } catch (e: any) {
      onError(e.message || "Could not change status.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className="linkbtn"
        aria-label={`Change status for ${application.job_title} at ${application.company}`}
        onClick={() => setOpen(true)}
      >
        Change Status
      </button>
    );
  }

  return (
    <label className="field-label" style={{ margin: 0 }}>
      <span className="sr-only">New status for {application.job_title}</span>
      <select
        className="field"
        autoFocus
        disabled={busy}
        value={application.status}
        onChange={(e) => apply(e.target.value as ApplicationStatus)}
        onBlur={() => setOpen(false)}
      >
        {STATUS_VALUES.map((s) => (
          <option key={s} value={s}>
            {STATUS_LABELS[s]}
          </option>
        ))}
      </select>
    </label>
  );
}
