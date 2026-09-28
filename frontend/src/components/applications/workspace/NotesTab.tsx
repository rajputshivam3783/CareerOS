"use client";

import { FormEvent, useEffect, useState } from "react";
import Modal from "@/components/common/Modal";
import { SkeletonLines } from "@/components/Skeleton";
import { ApplicationNote, createNote, deleteNote, fetchNotes, updateNote } from "@/lib/applicationWorkspace";

export default function NotesTab({ applicationId }: { applicationId: number }) {
  const [notes, setNotes] = useState<ApplicationNote[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<ApplicationNote | "new" | null>(null);

  async function load() {
    try {
      setNotes(await fetchNotes(applicationId));
    } catch (e: any) {
      setError(e.message || "Could not load notes.");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId]);

  async function handleDelete(id: number) {
    if (!confirm("Delete this note? This cannot be undone.")) return;
    try {
      await deleteNote(applicationId, id);
      await load();
    } catch (e: any) {
      setError(e.message || "Could not delete this note.");
    }
  }

  if (notes === null) return <SkeletonLines count={3} />;

  return (
    <div>
      {error && <p className="error">{error}</p>}
      <div className="actions" style={{ marginBottom: 14 }}>
        <button className="btn" onClick={() => setEditing("new")}>
          Add Note
        </button>
      </div>

      {notes.length === 0 ? (
        <div className="emptystate">
          <b>No notes yet</b>
          Keep track of recruiter conversations, interview prep, or company research here.
        </div>
      ) : (
        notes.map((n) => (
          <div key={n.id} className="wk-item">
            <div className="wk-item-main">
              <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{n.content}</p>
              <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>
                {n.updated_at && n.updated_at !== n.created_at ? "Edited " : "Added "}
                {new Date(n.updated_at || n.created_at).toLocaleString()}
              </p>
            </div>
            <div className="wk-item-actions">
              <button className="linkbtn" onClick={() => setEditing(n)} aria-label="Edit note">
                Edit
              </button>
              <button className="linkbtn danger" onClick={() => handleDelete(n.id)} aria-label="Delete note">
                Delete
              </button>
            </div>
          </div>
        ))
      )}

      {editing && (
        <NoteForm
          applicationId={applicationId}
          note={editing === "new" ? null : editing}
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

function NoteForm({
  applicationId,
  note,
  onClose,
  onSaved,
}: {
  applicationId: number;
  note: ApplicationNote | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [content, setContent] = useState(note?.content || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!content.trim()) {
      setError("Note content cannot be empty.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (note) await updateNote(applicationId, note.id, content);
      else await createNote(applicationId, content);
      onSaved();
    } catch (e: any) {
      setError(e.message || "Could not save this note.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={note ? "Edit Note" : "Add Note"} onClose={onClose}>
      <form className="form" onSubmit={handleSubmit}>
        {error && <p className="error" role="alert">{error}</p>}
        <label className="field-label">
          Content
          <textarea
            className="field"
            rows={6}
            required
            autoFocus
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="e.g. Recruiter called, discussed timeline and salary range..."
          />
        </label>
        <div className="actions">
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Saving..." : "Save Note"}
          </button>
          <button className="btn secondary" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
