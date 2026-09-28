"use client";

import { ChangeEvent, useEffect, useRef, useState } from "react";
import { SkeletonLines } from "@/components/Skeleton";
import {
  ApplicationDocument,
  DOCUMENT_CATEGORIES,
  DocumentCategory,
  deleteDocument,
  downloadDocument,
  fetchDocuments,
  formatFileSize,
  uploadDocument,
} from "@/lib/applicationWorkspace";

const CATEGORY_LABELS: Record<string, string> = {
  RESUME: "Resume",
  COVER_LETTER: "Cover Letter",
  PORTFOLIO: "Portfolio",
  CERTIFICATE: "Certificate",
  ASSESSMENT: "Assessment",
  OFFER_LETTER: "Offer Letter",
  OTHER: "Other",
};

export default function DocumentsTab({ applicationId }: { applicationId: number }) {
  const [docs, setDocs] = useState<ApplicationDocument[] | null>(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState<DocumentCategory>("RESUME");
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function load() {
    try {
      setDocs(await fetchDocuments(applicationId));
    } catch (e: any) {
      setError(e.message || "Could not load documents.");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId]);

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await uploadDocument(applicationId, category, file);
      await load();
    } catch (err: any) {
      setError(err.message || "Could not upload this document.");
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDownload(doc: ApplicationDocument) {
    try {
      await downloadDocument(applicationId, doc);
    } catch (e: any) {
      setError(e.message || "Could not download this document.");
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this document? This cannot be undone.")) return;
    try {
      await deleteDocument(applicationId, id);
      await load();
    } catch (e: any) {
      setError(e.message || "Could not delete this document.");
    }
  }

  if (docs === null) return <SkeletonLines count={3} />;

  return (
    <div>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ marginTop: 0 }}>Upload Document</h2>
        <div className="row" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
          <label className="field-label" style={{ minWidth: 200 }}>
            Category
            <select className="field" value={category} onChange={(e) => setCategory(e.target.value as DocumentCategory)}>
              {DOCUMENT_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_LABELS[c]}
                </option>
              ))}
            </select>
          </label>
          <label className="field-label" style={{ flex: 1, minWidth: 220 }}>
            File (PDF, Word, image, or text — up to 10 MB)
            <input
              ref={fileInputRef}
              className="field"
              type="file"
              accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg"
              onChange={handleFileChange}
              disabled={busy}
              aria-label="Choose a file to upload"
            />
          </label>
        </div>
        {busy && <p className="muted">Uploading...</p>}
      </div>

      {docs.length === 0 ? (
        <div className="emptystate">
          <b>No documents yet</b>
          Attach your resume, cover letter, or offer letter to keep everything for this application in one place.
        </div>
      ) : (
        docs.map((d) => (
          <div key={d.id} className="wk-item">
            <div className="wk-item-main">
              <b>{d.original_filename}</b>
              <p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>
                <span className="pill">{CATEGORY_LABELS[d.category]}</span> · {formatFileSize(d.file_size)} · {new Date(d.uploaded_at).toLocaleDateString()}
              </p>
            </div>
            <div className="wk-item-actions">
              <button className="linkbtn" onClick={() => handleDownload(d)} aria-label={`Download ${d.original_filename}`}>
                Download
              </button>
              <button className="linkbtn danger" onClick={() => handleDelete(d.id)} aria-label={`Delete ${d.original_filename}`}>
                Delete
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
