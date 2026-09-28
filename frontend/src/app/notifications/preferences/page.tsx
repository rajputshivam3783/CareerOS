"use client";
// V19.4 — Notification preferences (email/in-app on/off, category &
// organization free-text filters, quiet hours, digest mode). Backed by
// GET/PUT /notifications/preferences, which lazily creates a
// UserNotificationPreference row defaulted to "everything on,
// instant" — so this page always has something sensible to render
// even for a user who's never visited it before.
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, formatApiError } from "@/lib/api";

const DIGEST_OPTIONS = [
  { value: "instant", label: "Instant alerts" },
  { value: "daily_digest", label: "Daily digest" },
  { value: "weekly_summary", label: "Weekly summary" },
];

// V23.1 (in-app) / V23.2 (email) — per-category toggles. Security-
// critical email (verification, password reset) is never in this
// list — those always send regardless of these preferences.
const CATEGORIES = [
  { key: "job", label: "Job matches & alerts" },
  { key: "application", label: "Application updates" },
  { key: "interview", label: "Interviews" },
  { key: "deadline", label: "Deadlines" },
  { key: "recruiter", label: "Recruiter activity" },
  { key: "ai", label: "AI insights" },
  { key: "system", label: "System notifications" },
];

export default function Page() {
  const [prefs, setPrefs] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api("/notifications/preferences")
      .then(setPrefs)
      .catch((e) => {
        if (String(e.message || "").includes("401")) { location.href = "/login"; return; }
        setError(formatApiError(e.message, "Couldn't load preferences"));
      })
      .finally(() => setLoading(false));
  }, []);

  function set(key: string, value: any) { setPrefs((p: any) => ({ ...p, [key]: value })); setSaved(false); }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const payload = {
        email_enabled: prefs.email_enabled,
        in_app_enabled: prefs.in_app_enabled,
        category_preferences: prefs.category_preferences || null,
        organization_preferences: prefs.organization_preferences || null,
        quiet_hours_start: prefs.quiet_hours_start === "" ? null : prefs.quiet_hours_start,
        quiet_hours_end: prefs.quiet_hours_end === "" ? null : prefs.quiet_hours_end,
        digest_mode: prefs.digest_mode,
        digest_enabled: !!prefs.digest_enabled,
        timezone: prefs.timezone || "UTC",
        ...Object.fromEntries(CATEGORIES.flatMap((c) => [[`notify_${c.key}`, prefs[`notify_${c.key}`]], [`email_${c.key}`, prefs[`email_${c.key}`]]])),
      };
      const updated = await api("/notifications/preferences", { method: "PUT", body: JSON.stringify(payload) });
      setPrefs(updated);
      setSaved(true);
    } catch (e: any) {
      setError(formatApiError(e.message, "Couldn't save preferences"));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <main className="container page"><p className="muted">Loading…</p></main>;
  if (!prefs) return <main className="container page"><p className="error">{error}</p></main>;

  return (
    <main className="container narrow">
      <span className="eyebrow">Notification center</span>
      <h1 style={{ fontSize: 34, margin: "8px 0 22px" }}>Notification preferences</h1>

      <form className="form" onSubmit={save}>
        <label className="checkbox-label">
          <input type="checkbox" checked={prefs.email_enabled} onChange={(e) => set("email_enabled", e.target.checked)} />
          Email notifications
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={prefs.in_app_enabled} onChange={(e) => set("in_app_enabled", e.target.checked)} />
          In-app notifications
        </label>

        <h2 style={{ fontSize: 16, margin: "20px 0 8px" }}>By category</h2>
        <p className="muted" style={{ fontSize: 13, margin: "0 0 10px" }}>
          Email verification and password reset always send regardless of these settings.
        </p>
        <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 20 }}>
          <thead>
            <tr style={{ textAlign: "left", fontSize: 12, color: "var(--muted)" }}>
              <th style={{ padding: "4px 0" }}>Category</th>
              <th style={{ padding: "4px 0", width: 80 }}>In-app</th>
              <th style={{ padding: "4px 0", width: 80 }}>Email</th>
            </tr>
          </thead>
          <tbody>
            {CATEGORIES.map((c) => (
              <tr key={c.key} style={{ borderTop: "1px solid var(--line)" }}>
                <td style={{ padding: "8px 0", fontSize: 14 }}>{c.label}</td>
                <td style={{ padding: "8px 0" }}>
                  <input
                    type="checkbox"
                    aria-label={`In-app notifications for ${c.label}`}
                    checked={!!prefs[`notify_${c.key}`]}
                    onChange={(e) => set(`notify_${c.key}`, e.target.checked)}
                  />
                </td>
                <td style={{ padding: "8px 0" }}>
                  <input
                    type="checkbox"
                    aria-label={`Email notifications for ${c.label}`}
                    checked={!!prefs[`email_${c.key}`]}
                    onChange={(e) => set(`email_${c.key}`, e.target.checked)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <label className="field-label">
          Delivery frequency
          <select className="field" value={prefs.digest_mode} onChange={(e) => set("digest_mode", e.target.value)}>
            {DIGEST_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>

        {/* V23.4 — Communication Center daily digest email (a separate
            opt-in from the per-category toggles above: one bundled
            email covering everything that needs attention, rather
            than one email per event). Off by default for every user
            until they turn it on here. */}
        <label className="checkbox-label">
          <input type="checkbox" checked={!!prefs.digest_enabled} onChange={(e) => set("digest_enabled", e.target.checked)} />
          Daily career digest email (a summary of what needs your attention, sent once a day)
        </label>

        <label className="field-label">
          Timezone (used for quiet hours and the daily digest)
          <input
            className="field" value={prefs.timezone || "UTC"}
            onChange={(e) => set("timezone", e.target.value)}
            placeholder="e.g. Asia/Kolkata, America/New_York"
          />
        </label>

        <label className="field-label">
          Category preferences (comma-separated, e.g. "Bank, Railway")
          <input className="field" value={prefs.category_preferences || ""} onChange={(e) => set("category_preferences", e.target.value)} />
        </label>

        <label className="field-label">
          Organization preferences (comma-separated, e.g. "SSC, UPSC")
          <input className="field" value={prefs.organization_preferences || ""} onChange={(e) => set("organization_preferences", e.target.value)} />
        </label>

        <div className="grid2">
          <label className="field-label">
            Quiet hours start (0–23, local hour, email only)
            <input className="field" type="number" min={0} max={23} value={prefs.quiet_hours_start ?? ""}
                   onChange={(e) => set("quiet_hours_start", e.target.value === "" ? null : Number(e.target.value))} />
          </label>
          <label className="field-label">
            Quiet hours end
            <input className="field" type="number" min={0} max={23} value={prefs.quiet_hours_end ?? ""}
                   onChange={(e) => set("quiet_hours_end", e.target.value === "" ? null : Number(e.target.value))} />
          </label>
        </div>

        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button className="btn" type="submit" disabled={saving}>{saving ? "Saving…" : "Save preferences"}</button>
          {saved && <span className="verified">Saved</span>}
          <Link href="/communication" className="linkbtn">Communication Center</Link>
          <Link href="/notifications" className="linkbtn">Back to notifications</Link>
        </div>
      </form>
    </main>
  );
}
