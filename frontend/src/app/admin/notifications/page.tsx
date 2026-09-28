"use client";
// V19.4 — Automation & Notification Engine admin console. Same
// X-Admin-Key-or-session pattern as src/app/admin/government/page.tsx
// (additive new route, doesn't touch that page).
import { useEffect, useState } from "react";
import { API, formatApiError, token } from "@/lib/api";

type Tab = "queue" | "stats" | "logs" | "templates" | "health";
const TABS: { key: Tab; label: string }[] = [
  { key: "queue", label: "Delivery queue" }, { key: "stats", label: "Statistics" },
  { key: "logs", label: "Automation logs" }, { key: "templates", label: "Templates" },
  { key: "health", label: "Scheduler health" },
];

export default function NotificationAdminPage() {
  const [key, setKey] = useState("");
  const [hasSession, setHasSession] = useState(false);
  const [tab, setTab] = useState<Tab>("queue");
  const [msg, setMsg] = useState("");

  const [queue, setQueue] = useState<{ items: any[]; total: number }>({ items: [], total: 0 });
  const [stats, setStats] = useState<any>(null);
  const [logs, setLogs] = useState<{ items: any[]; total: number }>({ items: [], total: 0 });
  const [templates, setTemplates] = useState<any[]>([]);
  const [health, setHealth] = useState<Record<string, any>>({});
  const [editing, setEditing] = useState<{ key: string; channel: string; subject: string; body: string } | null>(null);

  useEffect(() => { setHasSession(!!token()); }, []);

  async function call(path: string, method = "GET", body?: any) {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const t = token(); if (t) headers["Authorization"] = `Bearer ${t}`;
    if (key) headers["X-Admin-Key"] = key;
    const r = await fetch(`${API}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let j: any = null; try { j = await r.json(); } catch {}
    if (!r.ok) throw new Error(formatApiError(j, "Admin request failed"));
    return j;
  }

  async function loadQueue() { setQueue(await call("/admin/notifications/queue")); }
  async function loadStats() { setStats(await call("/admin/notifications/stats")); }
  async function loadLogs() { setLogs(await call("/admin/automation/logs")); }
  async function loadTemplates() { setTemplates(await call("/admin/notification-templates")); }
  async function loadHealth() { setHealth(await call("/admin/automation/health")); }

  async function openWorkspace() {
    try {
      setMsg("");
      await Promise.all([loadQueue(), loadStats(), loadLogs(), loadTemplates(), loadHealth()]);
    } catch (e: any) { setMsg(e.message); }
  }

  async function retry(id: number) {
    try { await call(`/admin/notifications/${id}/retry`, "POST"); loadQueue(); loadStats(); } catch (e: any) { setMsg(e.message); }
  }

  async function runAll() {
    try { setMsg("Running…"); const r = await call("/admin/automation/run", "POST"); setMsg(`Automation run complete: ${r.total_notifications} notification(s) sent, ${r.reminders_fired} reminder(s) fired.`); await openWorkspace(); } catch (e: any) { setMsg(e.message); }
  }
  async function runOne(jobId: string) {
    try { setMsg(`Running ${jobId}…`); await call(`/admin/automation/run/${jobId}`, "POST"); setMsg(`${jobId} complete.`); loadHealth(); } catch (e: any) { setMsg(e.message); }
  }

  function startEdit(t: any) { setEditing({ key: t.key, channel: t.channel, subject: t.subject || "", body: t.body }); }
  async function saveTemplate() {
    if (!editing) return;
    try {
      await call(`/admin/notification-templates/${editing.key}/${editing.channel}`, "PUT", {
        subject: editing.channel === "email" ? editing.subject : null, body: editing.body, active: true,
      });
      setEditing(null);
      loadTemplates();
    } catch (e: any) { setMsg(e.message); }
  }

  return (
    <main className="container page">
      <span className="eyebrow">Government automation & notification engine — admin</span>
      <h1>Notification engine</h1>

      <div className="card form">
        {hasSession
          ? <p className="muted">Signed in as admin — using your session automatically.</p>
          : <label className="field-label">Admin key
              <input className="field" type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="X-Admin-Key" />
            </label>}
        <div className="actions">
          <button className="btn" onClick={openWorkspace}>Load workspace</button>
          <button className="btn secondary" onClick={runAll}>Run automation + reminders now</button>
        </div>
        {msg && <p className="muted">{msg}</p>}
      </div>

      <div className="filters">
        {TABS.map((t) => <button key={t.key} className={`chip ${tab === t.key ? "chip-active" : ""}`} onClick={() => setTab(t.key)}>{t.label}</button>)}
      </div>

      {tab === "queue" && (
        <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
          {queue.items.map((row) => (
            <div className="card row" key={row.id}>
              <div>
                <span className="pill">{row.channel}</span>
                <span className={`badge badge-${row.status === "sent" ? "active" : row.status === "failed" ? "open" : "paused"}`} style={{ marginLeft: 8 }}>{row.status}</span>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>user #{row.user_id} · provider {row.provider || "—"} · attempts {row.attempt_count}</div>
                {row.error && <div className="error" style={{ fontSize: 13 }}>{row.error}</div>}
              </div>
              {(row.status === "failed" || row.status === "not_implemented") && <button className="linkbtn" onClick={() => retry(row.id)}>Retry</button>}
            </div>
          ))}
          {!queue.items.length && <div className="empty">No deliveries yet.</div>}
        </div>
      )}

      {tab === "stats" && stats && (
        <div className="metrics">
          <div className="metric"><b>{stats.total_in_app_notifications}</b><span>Total in-app notifications</span></div>
          <div className="metric"><b>{stats.unread_in_app_notifications}</b><span>Unread</span></div>
          <div className="metric"><b>{stats.delivery_by_status?.sent || 0}</b><span>Deliveries sent</span></div>
          {Object.entries(stats.delivery_by_channel || {}).map(([ch, count]: any) => (
            <div className="metric" key={ch}><b>{count}</b><span>via {ch}</span></div>
          ))}
        </div>
      )}

      {tab === "logs" && (
        <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
          {logs.items.map((row) => (
            <div className="card" key={row.id}>
              <span className="pill">{row.trigger}</span>
              <p className="muted" style={{ marginTop: 8 }}>{row.detail}</p>
              <span className="muted" style={{ fontSize: 12 }}>{new Date(row.created_at).toLocaleString()}</span>
            </div>
          ))}
          {!logs.items.length && <div className="empty">No automation runs logged yet.</div>}
        </div>
      )}

      {tab === "templates" && (
        <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
          {editing && (
            <div className="card form">
              <h2>{editing.key} — {editing.channel}</h2>
              {editing.channel === "email" && (
                <label className="field-label">Subject
                  <input className="field" value={editing.subject} onChange={(e) => setEditing({ ...editing, subject: e.target.value })} />
                </label>
              )}
              <label className="field-label">Body
                <textarea className="field" rows={4} value={editing.body} onChange={(e) => setEditing({ ...editing, body: e.target.value })} />
              </label>
              <div className="actions">
                <button className="btn" onClick={saveTemplate}>Save template</button>
                <button className="linkbtn" onClick={() => setEditing(null)}>Cancel</button>
              </div>
            </div>
          )}
          {templates.map((t) => (
            <div className="card row" key={`${t.key}:${t.channel}`}>
              <div>
                <span className="pill">{t.channel}</span>
                <span className="strong" style={{ marginLeft: 8 }}>{t.key}</span>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>{t.subject || t.body.slice(0, 80)}</div>
              </div>
              <button className="linkbtn" onClick={() => startEdit(t)}>Edit</button>
            </div>
          ))}
        </div>
      )}

      {tab === "health" && (
        <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
          {["careeros_notifications", "careeros_automation", "careeros_reminder_sync", "careeros_ingestion"].map((jobId) => {
            const h = health[jobId];
            return (
              <div className="card row" key={jobId}>
                <div>
                  <span className="strong">{jobId}</span>
                  <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                    {h ? `Last run ${new Date(h.last_run_at).toLocaleString()} — ${h.ok ? "OK" : `failed: ${h.detail}`}` : "Not run yet"}
                  </div>
                </div>
                <button className="linkbtn" onClick={() => runOne(jobId)}>Run now</button>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
