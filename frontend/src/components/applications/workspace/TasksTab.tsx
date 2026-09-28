"use client";

import { FormEvent, useEffect, useState } from "react";
import Modal from "@/components/common/Modal";
import { SkeletonLines } from "@/components/Skeleton";
import { ApplicationTask, TaskInput, createTask, deleteTask, fetchTasks, setTaskCompleted, updateTask } from "@/lib/applicationWorkspace";

export default function TasksTab({ applicationId }: { applicationId: number }) {
  const [tasksList, setTasksList] = useState<ApplicationTask[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<ApplicationTask | "new" | null>(null);

  async function load() {
    try {
      setTasksList(await fetchTasks(applicationId));
    } catch (e: any) {
      setError(e.message || "Could not load tasks.");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId]);

  async function handleToggle(task: ApplicationTask) {
    try {
      await setTaskCompleted(applicationId, task.id, !task.completed);
      await load();
    } catch (e: any) {
      setError(e.message || "Could not update this task.");
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this task? This cannot be undone.")) return;
    try {
      await deleteTask(applicationId, id);
      await load();
    } catch (e: any) {
      setError(e.message || "Could not delete this task.");
    }
  }

  if (tasksList === null) return <SkeletonLines count={3} />;

  const overdueCount = tasksList.filter((t) => t.overdue).length;

  return (
    <div>
      {error && <p className="error">{error}</p>}
      <div className="row" style={{ marginBottom: 14 }}>
        <button className="btn" onClick={() => setEditing("new")}>
          Add Task
        </button>
        {overdueCount > 0 && <span className="badge badge-negative">{overdueCount} overdue</span>}
      </div>

      {tasksList.length === 0 ? (
        <div className="emptystate">
          <b>No tasks yet</b>
          Add follow-ups like &quot;Send recruiter follow-up&quot; or &quot;Prepare for technical interview&quot;.
        </div>
      ) : (
        tasksList.map((t) => (
          <div key={t.id} className={`wk-item ${t.completed ? "completed" : t.overdue ? "overdue" : ""}`}>
            <div className="wk-checkbox wk-item-main">
              <input
                type="checkbox"
                checked={t.completed}
                onChange={() => handleToggle(t)}
                aria-label={t.completed ? `Mark "${t.title}" as not completed` : `Mark "${t.title}" as completed`}
              />
              <div>
                <b style={{ textDecoration: t.completed ? "line-through" : "none" }}>{t.title}</b>
                {t.description && <p style={{ margin: "4px 0" }}>{t.description}</p>}
                <p className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>
                  {t.completed
                    ? `Completed ${t.completed_at ? new Date(t.completed_at).toLocaleString() : ""}`
                    : t.due_at
                    ? `${t.overdue ? "Overdue — was due" : "Due"} ${new Date(t.due_at).toLocaleString()}`
                    : "No due date"}
                </p>
              </div>
            </div>
            <div className="wk-item-actions">
              <button className="linkbtn" onClick={() => setEditing(t)} aria-label={`Edit task ${t.title}`}>
                Edit
              </button>
              <button className="linkbtn danger" onClick={() => handleDelete(t.id)} aria-label={`Delete task ${t.title}`}>
                Delete
              </button>
            </div>
          </div>
        ))
      )}

      {editing && (
        <TaskForm
          applicationId={applicationId}
          task={editing === "new" ? null : editing}
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

function TaskForm({
  applicationId,
  task,
  onClose,
  onSaved,
}: {
  applicationId: number;
  task: ApplicationTask | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState(task?.title || "");
  const [description, setDescription] = useState(task?.description || "");
  const [dueAt, setDueAt] = useState(task?.due_at ? task.due_at.slice(0, 16) : "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      setError("Task title cannot be empty.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload: TaskInput = { title, description: description || undefined, due_at: dueAt || undefined };
      if (task) await updateTask(applicationId, task.id, payload);
      else await createTask(applicationId, payload);
      onSaved();
    } catch (e: any) {
      setError(e.message || "Could not save this task.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={task ? "Edit Task" : "Add Task"} onClose={onClose}>
      <form className="form" onSubmit={handleSubmit}>
        {error && <p className="error" role="alert">{error}</p>}
        <label className="field-label">
          Title
          <input className="field" required autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Send recruiter follow-up" />
        </label>
        <label className="field-label">
          Description
          <textarea className="field" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label className="field-label">
          Due date
          <input className="field" type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} />
        </label>
        <div className="actions">
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Saving..." : "Save Task"}
          </button>
          <button className="btn secondary" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
