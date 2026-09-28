"use client";
import { safeHref } from "@/lib/safe";

import { FormEvent, useEffect, useState } from "react";
import Modal from "@/components/common/Modal";
import { SkeletonLines } from "@/components/Skeleton";
import {
  ApplicationInterview,
  INTERVIEW_RESULTS,
  INTERVIEW_TYPES,
  InterviewInput,
  createInterview,
  deleteInterview,
  fetchInterviews,
  updateInterview,
} from "@/lib/applicationWorkspace";

const TYPE_LABELS: Record<string, string> = {
  PHONE: "Phone",
  VIDEO: "Video",
  TECHNICAL: "Technical",
  HR: "HR",
  MANAGERIAL: "Managerial",
  ASSESSMENT: "Assessment",
  ONSITE: "Onsite",
  OTHER: "Other",
};

const RESULT_BADGE: Record<string, string> = {
  SCHEDULED: "badge-progress",
  COMPLETED: "badge-active",
  PASSED: "badge-success",
  FAILED: "badge-negative",
  CANCELLED: "badge-disabled",
  RESCHEDULED: "badge-paused",
};

export default function InterviewsTab({ applicationId }: { applicationId: number }) {
  const [interviews, setInterviews] = useState<ApplicationInterview[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<ApplicationInterview | "new" | null>(null);

  async function load() {
    try {
      setInterviews(await fetchInterviews(applicationId));
    } catch (e: any) {
      setError(e.message || "Could not load interviews.");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId]);

  async function handleDelete(id: number) {
    if (!confirm("Delete this interview record? This cannot be undone.")) return;
    try {
      await deleteInterview(applicationId, id);
      await load();
    } catch (e: any) {
      setError(e.message || "Could not delete this interview.");
    }
  }

  if (interviews === null) return <SkeletonLines count={3} />;

  return (
    <div>
      {error && <p className="error">{error}</p>}
      <div className="actions" style={{ marginBottom: 14 }}>
        <button className="btn" onClick={() => setEditing("new")}>
          Add Interview
        </button>
      </div>

      {interviews.length === 0 ? (
        <div className="emptystate">
          <b>No interviews recorded yet</b>
          Track each round — phone screen, technical, onsite — with its own schedule and result.
        </div>
      ) : (
        interviews.map((iv) => (
          <div key={iv.id} className="wk-item">
            <div className="wk-item-main">
              <b>
                {iv.round_name || TYPE_LABELS[iv.interview_type]} <span className={`badge ${RESULT_BADGE[iv.result] || ""}`}>{iv.result}</span>
              </b>
              <p className="muted" style={{ margin: "4px 0" }}>
                {TYPE_LABELS[iv.interview_type]}
                {iv.scheduled_at ? ` · ${new Date(iv.scheduled_at).toLocaleString()}` : ""}
                {iv.duration_minutes ? ` · ${iv.duration_minutes} min` : ""}
              </p>
              {(iv.interviewer_name || iv.interviewer_email) && (
                <p style={{ margin: "2px 0", fontSize: 13 }}>
                  {iv.interviewer_name} {iv.interviewer_email ? `(${iv.interviewer_email})` : ""}
                </p>
              )}
              {iv.meeting_url && (
                <p style={{ margin: "2px 0", fontSize: 13 }}>
                  <a href={safeHref(iv.meeting_url)} target="_blank" rel="noreferrer">
                    Meeting link →
                  </a>
                </p>
              )}
              {iv.location && <p style={{ margin: "2px 0", fontSize: 13 }}>{iv.location}</p>}
              {iv.notes && <p style={{ margin: "6px 0 0", fontSize: 13 }}>{iv.notes}</p>}
            </div>
            <div className="wk-item-actions">
              <button className="linkbtn" onClick={() => setEditing(iv)} aria-label={`Edit ${iv.round_name || iv.interview_type} interview`}>
                Edit
              </button>
              <button className="linkbtn danger" onClick={() => handleDelete(iv.id)} aria-label={`Delete ${iv.round_name || iv.interview_type} interview`}>
                Delete
              </button>
            </div>
          </div>
        ))
      )}

      {editing && (
        <InterviewForm
          applicationId={applicationId}
          interview={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await load();
          }}
        />
      )}
    </div>
  );
}

function InterviewForm({
  applicationId,
  interview,
  onClose,
  onSaved,
}: {
  applicationId: number;
  interview: ApplicationInterview | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<InterviewInput>({
    interview_type: interview?.interview_type || "PHONE",
    round_name: interview?.round_name || "",
    scheduled_at: interview?.scheduled_at ? interview.scheduled_at.slice(0, 16) : "",
    duration_minutes: interview?.duration_minutes ?? undefined,
    interviewer_name: interview?.interviewer_name || "",
    interviewer_email: interview?.interviewer_email || "",
    meeting_url: interview?.meeting_url || "",
    location: interview?.location || "",
    notes: interview?.notes || "",
    result: interview?.result || "SCHEDULED",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function set<K extends keyof InterviewInput>(key: K, value: InterviewInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload: InterviewInput = {
        ...form,
        round_name: form.round_name || undefined,
        scheduled_at: form.scheduled_at || undefined,
        interviewer_name: form.interviewer_name || undefined,
        interviewer_email: form.interviewer_email || undefined,
        meeting_url: form.meeting_url || undefined,
        location: form.location || undefined,
        notes: form.notes || undefined,
      };
      if (interview) await updateInterview(applicationId, interview.id, payload);
      else await createInterview(applicationId, payload);
      onSaved();
    } catch (e: any) {
      setError(e.message || "Could not save this interview.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={interview ? "Edit Interview" : "Add Interview"} onClose={onClose}>
      <form className="form" onSubmit={handleSubmit}>
        {error && <p className="error" role="alert">{error}</p>}
        <label className="field-label">
          Interview type
          <select className="field" value={form.interview_type} onChange={(e) => set("interview_type", e.target.value as InterviewInput["interview_type"])}>
            {INTERVIEW_TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </label>
        <label className="field-label">
          Round name
          <input className="field" value={form.round_name} onChange={(e) => set("round_name", e.target.value)} placeholder="e.g. Round 2 — Hiring Manager" />
        </label>
        <label className="field-label">
          Scheduled at
          <input className="field" type="datetime-local" value={form.scheduled_at} onChange={(e) => set("scheduled_at", e.target.value)} />
        </label>
        <label className="field-label">
          Duration (minutes)
          <input
            className="field"
            type="number"
            min={0}
            max={1440}
            value={form.duration_minutes ?? ""}
            onChange={(e) => set("duration_minutes", e.target.value ? Number(e.target.value) : undefined)}
          />
        </label>
        <label className="field-label">
          Interviewer name
          <input className="field" value={form.interviewer_name} onChange={(e) => set("interviewer_name", e.target.value)} />
        </label>
        <label className="field-label">
          Interviewer email
          <input className="field" type="email" value={form.interviewer_email} onChange={(e) => set("interviewer_email", e.target.value)} />
        </label>
        <label className="field-label">
          Meeting URL
          <input className="field" type="url" placeholder="https://..." value={form.meeting_url} onChange={(e) => set("meeting_url", e.target.value)} />
        </label>
        <label className="field-label">
          Location
          <input className="field" value={form.location} onChange={(e) => set("location", e.target.value)} />
        </label>
        <label className="field-label">
          Notes
          <textarea className="field" rows={3} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
        </label>
        <label className="field-label">
          Result
          <select className="field" value={form.result} onChange={(e) => set("result", e.target.value as InterviewInput["result"])}>
            {INTERVIEW_RESULTS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <div className="actions">
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Saving..." : "Save Interview"}
          </button>
          <button className="btn secondary" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
