"use client";
// V19.4 — "notify me about X" subscriptions. One generic form covers
// every subscription_type the spec lists (Organization / Exam /
// Category / Qualification / State / the flat Central-PSU-Bank-...
// checkboxes) — value-based types take a free-text value, the flat
// checkbox types need no value at all. Direct single-recruitment
// subscriptions are created from the job detail page, not here.
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, formatApiError } from "@/lib/api";

const VALUE_TYPES = [
  { value: "organization", label: "Organization", placeholder: "e.g. SSC" },
  { value: "exam", label: "Exam", placeholder: "e.g. CGL" },
  { value: "category", label: "Category", placeholder: "e.g. Judiciary" },
  { value: "qualification", label: "Qualification", placeholder: "e.g. Graduation" },
  { value: "state", label: "State (optional location filter)", placeholder: "e.g. Maharashtra — leave blank for all States" },
];
const FLAT_TYPES = [
  { value: "central", label: "Central Jobs" }, { value: "psu", label: "PSU" },
  { value: "bank", label: "Bank Jobs" }, { value: "railway", label: "Railway Jobs" },
  { value: "police", label: "Police Jobs" }, { value: "teaching", label: "Teaching Jobs" },
  { value: "medical", label: "Medical Jobs" }, { value: "engineering", label: "Engineering Jobs" },
  { value: "defence", label: "Defence Jobs" },
];
const LABELS: Record<string, string> = Object.fromEntries(
  [...VALUE_TYPES, ...FLAT_TYPES].map((t) => [t.value, t.label])
);

export default function Page() {
  const [subs, setSubs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [type, setType] = useState("organization");
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function load() {
    api("/subscriptions")
      .then(setSubs)
      .catch((e) => {
        if (String(e.message || "").includes("401")) { location.href = "/login"; return; }
        setError(formatApiError(e.message, "Couldn't load subscriptions"));
      })
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const isFlat = FLAT_TYPES.some((t) => t.value === type);
      await api("/subscriptions", {
        method: "POST",
        body: JSON.stringify({ subscription_type: type, value: isFlat ? null : value.trim() || null }),
      });
      setValue("");
      load();
    } catch (e: any) {
      setError(formatApiError(e.message, "Couldn't add subscription"));
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(id: number) {
    await api(`/subscriptions/${id}`, { method: "DELETE" });
    setSubs((prev) => prev.filter((s) => s.id !== id));
  }

  const isFlatSelected = FLAT_TYPES.some((t) => t.value === type);

  return (
    <main className="container narrow">
      <span className="eyebrow">Notification center</span>
      <h1 style={{ fontSize: 34, margin: "8px 0 22px" }}>Subscriptions</h1>
      <p className="muted">
        Get notified about new recruitments, admit cards, results and every other lifecycle update for the
        organizations, exams and categories you care about. Manage delivery via{" "}
        <Link href="/notifications/preferences" className="linkbtn">Preferences</Link>.
      </p>

      <form className="form" onSubmit={add} style={{ marginTop: 22 }}>
        <label className="field-label">
          Subscribe to
          <select className="field" value={type} onChange={(e) => { setType(e.target.value); setValue(""); }}>
            <optgroup label="Match by value">
              {VALUE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </optgroup>
            <optgroup label="Government-level / category">
              {FLAT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </optgroup>
          </select>
        </label>
        {!isFlatSelected && (
          <label className="field-label">
            Value
            <input className="field" value={value} onChange={(e) => setValue(e.target.value)}
                   placeholder={VALUE_TYPES.find((t) => t.value === type)?.placeholder}
                   required={type !== "state"} />
          </label>
        )}
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button className="btn" type="submit" disabled={submitting}>{submitting ? "Adding…" : "Add subscription"}</button>
        </div>
      </form>

      {loading && <p className="muted">Loading…</p>}
      <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 26 }}>
        {subs.map((s) => (
          <div className="card row" key={s.id}>
            <div>
              <span className="pill">{LABELS[s.subscription_type] || s.subscription_type}</span>
              {s.value && <span className="strong" style={{ marginLeft: 10 }}>{s.value}</span>}
              {s.job_id && <span className="strong" style={{ marginLeft: 10 }}>Job #{s.job_id}</span>}
            </div>
            <button className="linkbtn danger" onClick={() => remove(s.id)}>Remove</button>
          </div>
        ))}
      </div>
      {!loading && !subs.length && <div className="empty">No subscriptions yet — add one above.</div>}
    </main>
  );
}
