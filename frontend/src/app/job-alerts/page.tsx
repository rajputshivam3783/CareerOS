"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { formatApiError } from "@/lib/api";
import {
  JobAlert,
  JobAlertFormInput,
  JobAlertMatch,
  createJobAlert,
  deleteJobAlert,
  disableJobAlert,
  enableJobAlert,
  listJobAlerts,
  previewNewJobAlert,
  updateJobAlert,
} from "@/lib/jobAlerts";

const FREQUENCIES = ["INSTANT", "DAILY", "WEEKLY"];
const REMOTE_OPTIONS = [
  { value: "", label: "Any" },
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "Onsite" },
];
const GOVT_OPTIONS = [
  { value: "", label: "Any" },
  { value: "government", label: "Government" },
  { value: "private", label: "Private" },
];

const EMPTY_FORM: JobAlertFormInput = {
  name: "",
  keywords: "",
  job_title: "",
  skills: "",
  location: "",
  remote_preference: "",
  employment_type: "",
  experience_level: "",
  job_category: "",
  govt_private_preference: "",
  company: "",
  source: "",
  frequency: "INSTANT",
  use_profile_personalization: false,
  enabled: true,
};

function cleanPayload(form: JobAlertFormInput): JobAlertFormInput {
  // Empty strings mean "don't filter on this" (spec: every criterion is
  // optional) — send them as omitted rather than as empty-string filters.
  const out: JobAlertFormInput = {};
  for (const [k, v] of Object.entries(form)) {
    if (v === "" || v === undefined) continue;
    (out as any)[k] = v;
  }
  return out;
}

function AlertForm({
  initial,
  onCancel,
  onSaved,
}: {
  initial?: JobAlert;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<JobAlertFormInput>(
    initial
      ? {
          name: initial.name,
          keywords: initial.keywords || "",
          job_title: initial.job_title || "",
          skills: initial.skills || "",
          location: initial.location || "",
          remote_preference: initial.remote_preference || "",
          employment_type: initial.employment_type || "",
          experience_level: initial.experience_level || "",
          salary_min: initial.salary_min ?? undefined,
          salary_max: initial.salary_max ?? undefined,
          job_category: initial.job_category || "",
          govt_private_preference: initial.govt_private_preference || "",
          company: initial.company || "",
          source: initial.source || "",
          frequency: initial.frequency,
          min_relevance_score: initial.min_relevance_score ?? undefined,
          use_profile_personalization: initial.use_profile_personalization,
          enabled: initial.enabled,
        }
      : EMPTY_FORM
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [previewItems, setPreviewItems] = useState<JobAlertMatch[] | null>(null);
  const [previewError, setPreviewError] = useState("");

  function set<K extends keyof JobAlertFormInput>(key: K, value: JobAlertFormInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handlePreview() {
    setPreviewing(true);
    setPreviewError("");
    try {
      const payload = cleanPayload({ ...form, name: form.name || "preview" });
      const res = await previewNewJobAlert(payload);
      setPreviewItems(res.items);
    } catch (e) {
      setPreviewError(formatApiError(e, "Couldn't load preview"));
    } finally {
      setPreviewing(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name || !form.name.trim()) {
      setError("Alert name is required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload = cleanPayload(form);
      if (initial) await updateJobAlert(initial.id, payload);
      else await createJobAlert(payload);
      onSaved();
    } catch (e) {
      setError(formatApiError(e, "Couldn't save this alert"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="form card" onSubmit={handleSubmit}>
      <h2>{initial ? "Edit alert" : "Create job alert"}</h2>
      {error && <div className="error">{error}</div>}

      <label className="field-label">
        Alert name
        <input className="field" value={form.name || ""} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Remote Python roles in Noida" />
      </label>

      <div className="grid2">
        <label className="field-label">
          Keywords
          <input className="field" value={form.keywords || ""} onChange={(e) => set("keywords", e.target.value)} placeholder="e.g. backend developer" />
        </label>
        <label className="field-label">
          Location
          <input className="field" value={form.location || ""} onChange={(e) => set("location", e.target.value)} placeholder="e.g. Noida" />
        </label>
        <label className="field-label">
          Skills (comma separated)
          <input className="field" value={form.skills || ""} onChange={(e) => set("skills", e.target.value)} placeholder="e.g. Python, SQL, AWS" />
        </label>
        <label className="field-label">
          Employment type
          <input className="field" value={form.employment_type || ""} onChange={(e) => set("employment_type", e.target.value)} placeholder="e.g. Full-time" />
        </label>
        <label className="field-label">
          Experience
          <input className="field" value={form.experience_level || ""} onChange={(e) => set("experience_level", e.target.value)} placeholder="e.g. 2-4 years" />
        </label>
        <label className="field-label">
          Job category
          <input className="field" value={form.job_category || ""} onChange={(e) => set("job_category", e.target.value)} />
        </label>
        <label className="field-label">
          Company
          <input className="field" value={form.company || ""} onChange={(e) => set("company", e.target.value)} />
        </label>
        <label className="field-label">
          Remote preference
          <select className="field" value={form.remote_preference || ""} onChange={(e) => set("remote_preference", e.target.value)}>
            {REMOTE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <label className="field-label">
          Government / Private
          <select className="field" value={form.govt_private_preference || ""} onChange={(e) => set("govt_private_preference", e.target.value)}>
            {GOVT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <label className="field-label">
          Frequency
          <select className="field" value={form.frequency || "INSTANT"} onChange={(e) => set("frequency", e.target.value)}>
            {FREQUENCIES.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        <label className="field-label">
          Salary min
          <input className="field" type="number" min={0} value={form.salary_min ?? ""} onChange={(e) => set("salary_min", e.target.value ? Number(e.target.value) : undefined)} />
        </label>
        <label className="field-label">
          Salary max
          <input className="field" type="number" min={0} value={form.salary_max ?? ""} onChange={(e) => set("salary_max", e.target.value ? Number(e.target.value) : undefined)} />
        </label>
        <label className="field-label">
          Minimum relevance score (0-100, optional)
          <input className="field" type="number" min={0} max={100} value={form.min_relevance_score ?? ""} onChange={(e) => set("min_relevance_score", e.target.value ? Number(e.target.value) : undefined)} />
        </label>
      </div>

      <label className="checkbox-label">
        <input type="checkbox" checked={!!form.use_profile_personalization} onChange={(e) => set("use_profile_personalization", e.target.checked)} />
        Use my CareerOS profile to personalize matches and relevance scoring
      </label>

      <div className="actions">
        <button type="submit" className="btn" disabled={saving}>{saving ? "Saving…" : initial ? "Save changes" : "Create alert"}</button>
        <button type="button" className="secondary btn" onClick={handlePreview} disabled={previewing}>
          {previewing ? "Loading preview…" : "Preview matching jobs"}
        </button>
        <button type="button" className="linkbtn" onClick={onCancel}>Cancel</button>
      </div>

      {previewError && <div className="error">{previewError}</div>}
      {previewItems && (
        <div className="section">
          <h2 style={{ fontSize: 16 }}>Example jobs that match this alert</h2>
          {previewItems.length === 0 ? (
            <p className="muted">No current jobs match these criteria yet — you'll still be notified when a new one does.</p>
          ) : (
            <div className="qlist">
              {previewItems.map((m) => (
                <div key={m.job_id} className="qitem">
                  <div>
                    <b>{m.title}</b> — {m.organization}{m.location ? ` · ${m.location}` : ""}
                    <div className="muted" style={{ fontSize: 12 }}>{m.match_reasons.join(" · ")}</div>
                  </div>
                  <span className="pill">{m.relevance_score}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </form>
  );
}

function AlertCard({
  alert,
  onChanged,
  onEdit,
}: {
  alert: JobAlert;
  onChanged: () => void;
  onEdit: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function toggle() {
    setBusy(true);
    setError("");
    try {
      if (alert.enabled) await disableJobAlert(alert.id);
      else await enableJobAlert(alert.id);
      onChanged();
    } catch (e) {
      setError(formatApiError(e, "Couldn't update this alert"));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm(`Delete the alert "${alert.name}"? This can't be undone.`)) return;
    setBusy(true);
    setError("");
    try {
      await deleteJobAlert(alert.id);
      onChanged();
    } catch (e) {
      setError(formatApiError(e, "Couldn't delete this alert"));
      setBusy(false);
    }
  }

  const criteria = [
    alert.keywords,
    alert.location,
    alert.employment_type,
    alert.job_category,
    alert.govt_private_preference,
    alert.remote_preference,
  ].filter(Boolean);

  return (
    <div className="card">
      <div className="row">
        <div>
          <b>{alert.name}</b>{" "}
          <span className={`pill ${alert.enabled ? "" : "badge-disabled"}`}>{alert.enabled ? "Active" : "Disabled"}</span>{" "}
          <span className="pill">{alert.frequency}</span>
        </div>
        <div className="actions">
          <Link href={`/job-alerts/${alert.id}`} className="linkbtn">View matches</Link>
          <button className="linkbtn" onClick={onEdit} disabled={busy}>Edit</button>
          <button className="linkbtn" onClick={toggle} disabled={busy}>{alert.enabled ? "Disable" : "Enable"}</button>
          <button className="linkbtn danger" onClick={remove} disabled={busy}>Delete</button>
        </div>
      </div>
      {criteria.length > 0 && <p className="muted" style={{ marginTop: 8 }}>{criteria.join(" · ")}</p>}
      <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
        {alert.last_run_at
          ? `Last run ${new Date(alert.last_run_at).toLocaleString()} · ${alert.last_match_count} match(es) · ${alert.last_run_status}`
          : "Not run yet"}
      </p>
      {error && <div className="error">{error}</div>}
    </div>
  );
}

export default function JobAlertsPage() {
  const [alerts, setAlerts] = useState<JobAlert[] | null>(null);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<JobAlert | null>(null);

  async function load() {
    setError("");
    try {
      setAlerts(await listJobAlerts());
    } catch (e) {
      setError(formatApiError(e, "Couldn't load your job alerts"));
    }
  }

  useEffect(() => {
    load();
  }, []);

  function closeForm() {
    setShowForm(false);
    setEditing(null);
  }

  function onSaved() {
    closeForm();
    load();
  }

  return (
    <div className="page container">
      <div className="pagehead">
        <div>
          <p className="eyebrow">Smart job alerts</p>
          <h1>Job Alerts</h1>
        </div>
        {!showForm && !editing && (
          <button className="btn" onClick={() => setShowForm(true)}>Create Job Alert</button>
        )}
      </div>

      {(showForm || editing) && (
        <AlertForm initial={editing || undefined} onCancel={closeForm} onSaved={onSaved} />
      )}

      {error && <div className="error">{error}</div>}

      {alerts === null && !error && <p className="loading">Loading your job alerts…</p>}

      {alerts && alerts.length === 0 && !showForm && (
        <div className="empty card">
          <p>You don't have any job alerts yet.</p>
          <button className="btn" onClick={() => setShowForm(true)}>Create Job Alert</button>
        </div>
      )}

      {alerts && alerts.length > 0 && (
        <div className="form" style={{ marginTop: 20 }}>
          {alerts.map((a) => (
            <AlertCard
              key={a.id}
              alert={a}
              onChanged={load}
              onEdit={() => {
                setEditing(a);
                setShowForm(false);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
