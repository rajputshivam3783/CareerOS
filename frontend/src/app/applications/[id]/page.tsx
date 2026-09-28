"use client";
import { safeHref } from "@/lib/safe";

// V22.3 — Application Detail Workspace. Upgrades the V22.1 detail page
// (overview + status history) into a full tabbed workspace: Overview,
// Timeline, Notes, Interviews, Documents, Tasks. The overview/status
// logic below is unchanged from V22.1/V22.2 — only wrapped in a tab.

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import StatusBadge from "@/components/applications/StatusBadge";
import AIInsightsTab from "@/components/applications/workspace/AIInsightsTab";
import DocumentsTab from "@/components/applications/workspace/DocumentsTab";
import InterviewsTab from "@/components/applications/workspace/InterviewsTab";
import NotesTab from "@/components/applications/workspace/NotesTab";
import TasksTab from "@/components/applications/workspace/TasksTab";
import TimelineTab from "@/components/applications/workspace/TimelineTab";
import { isSignedIn } from "@/lib/bookmarks";
import {
  Application,
  ApplicationHistoryEntry,
  ApplicationStatus,
  REOPEN_REQUIRED_STATUSES,
  STATUS_LABELS,
  STATUS_VALUES,
  changeApplicationStatus,
  deleteApplication,
  fetchApplication,
  fetchApplicationHistory,
} from "@/lib/applications";

type Tab = "overview" | "timeline" | "notes" | "interviews" | "documents" | "tasks" | "ai";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "ai", label: "AI Insights" },
  { id: "timeline", label: "Timeline" },
  { id: "notes", label: "Notes" },
  { id: "interviews", label: "Interviews" },
  { id: "documents", label: "Documents" },
  { id: "tasks", label: "Tasks" },
];

export default function ApplicationDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = Number(params.id as string);

  const [tab, setTab] = useState<Tab>("overview");
  const [application, setApplication] = useState<Application | null>(null);
  const [history, setHistory] = useState<ApplicationHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [nextStatus, setNextStatus] = useState<ApplicationStatus | "">("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [app, hist] = await Promise.all([fetchApplication(id), fetchApplicationHistory(id)]);
      setApplication(app);
      setHistory(hist);
    } catch (e: any) {
      setError(e.message || "Could not load this application.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!isSignedIn()) {
      location.href = "/login";
      return;
    }
    if (id) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function handleStatusChange() {
    if (!nextStatus) return;
    setBusy(true);
    setError("");
    try {
      const isReopen = !!application && REOPEN_REQUIRED_STATUSES.includes(application.status) && application.status !== nextStatus;
      if (isReopen && !confirm(`"${STATUS_LABELS[application!.status]}" is a closed status. Reopen this application and move it to "${STATUS_LABELS[nextStatus]}"?`)) {
        setBusy(false);
        return;
      }
      await changeApplicationStatus(id, nextStatus, { note: note || undefined, reopen: isReopen });
      setNote("");
      setNextStatus("");
      await load();
    } catch (e: any) {
      setError(e.message || "Could not update the status.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!confirm("Delete this application? This cannot be undone.")) return;
    setBusy(true);
    try {
      await deleteApplication(id);
      router.push("/applications");
    } catch (e: any) {
      setError(e.message || "Could not delete this application.");
      setBusy(false);
    }
  }

  if (loading) return <main className="container page">Loading...</main>;
  if (error && !application) return <main className="container page"><p className="error">{error}</p></main>;
  if (!application) return null;

  const a = application;

  return (
    <main className="container page">
      <div className="pagehead">
        <div>
          <span className="eyebrow">Application</span>
          <h1>{a.job_title}</h1>
          <p className="muted">
            {a.company}
            {a.location ? ` · ${a.location}` : ""}
          </p>
        </div>
        <StatusBadge status={a.status} />
      </div>

      {error && <p className="error">{error}</p>}

      <div className="worktabs" role="tablist" aria-label="Application sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={`worktab ${tab === t.id ? "worktab-active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="workpanel" role="tabpanel">
        {tab === "overview" && (
          <div className="grid2">
            <div className="card">
              <h2>Details</h2>
              <p>
                <b>Source:</b> {a.source || "CareerOS"}
              </p>
              {a.job_url && (
                <p>
                  <b>Job link:</b>{" "}
                  <a href={safeHref(a.job_url)} target="_blank" rel="noreferrer">
                    {a.job_url}
                  </a>
                </p>
              )}
              {a.employment_type && (
                <p>
                  <b>Employment type:</b> {a.employment_type}
                </p>
              )}
              {a.salary && (
                <p>
                  <b>Salary:</b> {a.salary}
                </p>
              )}
              <p>
                <b>Applied:</b> {a.applied_at || "Not yet"}
              </p>
              {a.deadline && (
                <p>
                  <b>Deadline:</b> {a.deadline}
                </p>
              )}
              {a.next_deadline && (
                <p>
                  <b>Next action due:</b> {a.next_deadline}
                </p>
              )}
              {(a.recruiter_name || a.recruiter_email) && (
                <p>
                  <b>Contact:</b> {a.recruiter_name} {a.recruiter_email ? `(${a.recruiter_email})` : ""}
                </p>
              )}
              {a.external_reference && (
                <p>
                  <b>Reference:</b> {a.external_reference}
                </p>
              )}
              {a.notes && (
                <p>
                  <b>Notes:</b> {a.notes}
                </p>
              )}
              {a.job_id && (
                <p>
                  <a href={`/jobs/${a.job_id}`}>View original CareerOS listing →</a>
                </p>
              )}

              <div className="actions" style={{ marginTop: 16 }}>
                <button className="linkbtn danger" onClick={handleDelete} disabled={busy}>
                  Delete application
                </button>
              </div>
            </div>

            <div className="card">
              <h2>Update status</h2>
              <label className="field-label">
                New status
                <select className="field" value={nextStatus} onChange={(e) => setNextStatus(e.target.value as ApplicationStatus)}>
                  <option value="">Select a status...</option>
                  {STATUS_VALUES.map((s) => (
                    <option key={s} value={s}>
                      {STATUS_LABELS[s]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field-label">
                Note (optional)
                <input className="field" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. recruiter called" />
              </label>
              <button className="btn" onClick={handleStatusChange} disabled={busy || !nextStatus}>
                Update Status
              </button>

              <h2 style={{ marginTop: 24 }}>Status history</h2>
              {history.length === 0 && <p className="muted">No history yet.</p>}
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {history.map((h) => (
                  <div key={h.id} style={{ borderLeft: "3px solid var(--line)", paddingLeft: 10 }}>
                    <p style={{ margin: 0 }}>
                      {h.old_status ? `${STATUS_LABELS[h.old_status]} → ` : ""}
                      <b>{STATUS_LABELS[h.new_status]}</b>
                    </p>
                    <p className="muted" style={{ fontSize: 12, margin: 0 }}>
                      {new Date(h.changed_at).toLocaleString()}
                      {h.metadata?.note ? ` — ${h.metadata.note}` : ""}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === "ai" && <AIInsightsTab applicationId={a.id} />}
        {tab === "timeline" && <TimelineTab applicationId={a.id} />}
        {tab === "notes" && <NotesTab applicationId={a.id} />}
        {tab === "interviews" && <InterviewsTab applicationId={a.id} />}
        {tab === "documents" && <DocumentsTab applicationId={a.id} />}
        {tab === "tasks" && <TasksTab applicationId={a.id} />}
      </div>
    </main>
  );
}
