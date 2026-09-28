"use client";

// EXTERNAL APPLICATIONS — "Add Application" for a job found outside
// CareerOS. job_id stays null for anything created here (see
// app.applications.service.create_application).

import { FormEvent, useState } from "react";
import {
  ApplicationStatus,
  STATUS_LABELS,
  STATUS_VALUES,
  createExternalApplication,
} from "@/lib/applications";

export default function AddApplicationForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const [company, setCompany] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [jobUrl, setJobUrl] = useState("");
  const [location, setLocation] = useState("");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState<ApplicationStatus>("SAVED");
  const [appliedAt, setAppliedAt] = useState("");
  const [deadline, setDeadline] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await createExternalApplication({
        company,
        job_title: jobTitle,
        job_url: jobUrl || undefined,
        location: location || undefined,
        source: source || undefined,
        status,
        applied_at: appliedAt || undefined,
        deadline: deadline || undefined,
      });
      onCreated();
    } catch (err: any) {
      setError(err.message || "Could not add this application.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form card" onSubmit={handleSubmit}>
      <h2>Add Application</h2>
      {error && <p className="error">{error}</p>}

      <label className="field-label">
        Company *
        <input className="field" required value={company} onChange={(e) => setCompany(e.target.value)} />
      </label>
      <label className="field-label">
        Job title *
        <input className="field" required value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} />
      </label>
      <label className="field-label">
        Job URL
        <input className="field" type="url" placeholder="https://..." value={jobUrl} onChange={(e) => setJobUrl(e.target.value)} />
      </label>
      <label className="field-label">
        Location
        <input className="field" value={location} onChange={(e) => setLocation(e.target.value)} />
      </label>
      <label className="field-label">
        Source
        <input className="field" placeholder="LinkedIn, referral, company site..." value={source} onChange={(e) => setSource(e.target.value)} />
      </label>
      <label className="field-label">
        Status
        <select className="field" value={status} onChange={(e) => setStatus(e.target.value as ApplicationStatus)}>
          {STATUS_VALUES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </label>
      <label className="field-label">
        Application date
        <input className="field" type="date" value={appliedAt} onChange={(e) => setAppliedAt(e.target.value)} />
      </label>
      <label className="field-label">
        Deadline
        <input className="field" type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
      </label>

      <div className="actions">
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Adding..." : "Add Application"}
        </button>
        <button className="btn secondary" type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}
