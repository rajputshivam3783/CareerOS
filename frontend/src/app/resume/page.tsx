"use client";

import { useEffect, useState } from "react";
import { API, api, formatApiError, token } from "@/lib/api";

export default function Page() {
  const [resume, setResume] = useState<any>(null);
  const [jobId, setJobId] = useState("");
  const [matchResult, setMatchResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { setJobId(new URLSearchParams(window.location.search).get("job") || ""); }, []);

  async function load() {
    try {
      setResume(await api("/resume"));
    } catch {
      setResume(null);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function upload(file: File) {
    setBusy(true);
    setErr("");
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await fetch(`${API}/resume`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token()}` },
        body: form,
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(formatApiError(j, "Upload failed"));
      }
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeResume() {
    await api("/resume", { method: "DELETE" });
    setResume(null);
    setMatchResult(null);
  }

  async function runMatch() {
    setErr("");
    setMatchResult(null);
    try {
      setMatchResult(await api(`/resume-match/${jobId}`));
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <main className="container page">
      <span className="eyebrow">Career growth</span>
      <h1>Resume</h1>
      <p className="muted">Upload a PDF or DOCX resume to match it against any job's description.</p>
      {resume && <p><a href="/resume/intelligence">Open AI Resume Intelligence →</a></p>}

      <div className="card form">
        {!resume && (
          <label className="field-label">
            Upload resume (PDF, DOCX, or TXT)
            <input
              className="field"
              type="file"
              accept=".pdf,.docx,.txt"
              onChange={(e) => e.target.files && upload(e.target.files[0])}
              disabled={busy}
            />
          </label>
        )}

        {resume && (
          <>
            <p>
              <b>{resume.filename}</b> — {resume.characters_extracted} characters extracted
            </p>
            <p className="muted">Skills detected: {resume.skills_detected?.join(", ") || "none found"}</p>
            <div className="actions">
              <button className="btn secondary" onClick={removeResume}>
                Remove resume
              </button>
            </div>
          </>
        )}

        {err && <p className="error">{err}</p>}
      </div>

      {resume && (
        <div className="card form" style={{ marginTop: 20 }}>
          <h2>Match against a job</h2>
          <input
            className="field"
            type="number"
            placeholder="Job ID"
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
          />
          <button className="btn" onClick={runMatch}>
            Run resume match
          </button>

          {matchResult && (
            <div style={{ marginTop: 16 }}>
              <p>
                Match score: <b>{matchResult.score}%</b> ({matchResult.engine})
              </p>
              <p className="muted">Matched skills: {matchResult.matched_skills.join(", ") || "none"}</p>
              <p className="muted">Missing skills: {matchResult.missing_skills.join(", ") || "none"}</p>

              <h2>Learning roadmap</h2>
              <p><b>Now:</b> {matchResult.roadmap.immediate.join("; ") || "—"}</p>
              <p><b>Next:</b> {matchResult.roadmap.medium_term.join("; ") || "—"}</p>
              <p><b>Later:</b> {matchResult.roadmap.long_term.join("; ") || "—"}</p>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
