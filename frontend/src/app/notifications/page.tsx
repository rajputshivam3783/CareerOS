"use client";
// V19.4 — Notification Center. Replaces the minimal V7 page that lived
// at this same route (GET /notifications, mark read, mark all read
// only) with the full Notification Center the spec asks for, backed
// by the new GET /notifications/center (unread/read/archived + search
// + pagination) and the archive/delete actions added alongside it.
// Nav.tsx's unread badge keeps working unmodified — it reads the
// separate, untouched GET /notifications/unread-count endpoint.
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, formatApiError } from "@/lib/api";

const TYPE_LABEL: Record<string, string> = {
  deadline: "Deadline", admit_card: "Admit card", result: "Result", alert_match: "Saved alert",
  automation: "Automation",
  // V23.1 — event-driven types (see app/notifications/events.py)
  application_created: "Application", application_status_changed: "Application", interview_scheduled: "Interview", interview_updated: "Interview",
};
const PRIORITY_LABEL: Record<string, string> = { LOW: "Low priority", NORMAL: "", HIGH: "High priority", URGENT: "Urgent" };
const PRIORITY_ICON: Record<string, string> = { LOW: "", NORMAL: "", HIGH: "\u26a0", URGENT: "\u2757" };

type Tab = "unread" | "read" | "archived" | "all";
const TABS: { key: Tab; label: string }[] = [
  { key: "unread", label: "Unread" }, { key: "read", label: "Read" },
  { key: "archived", label: "Archive" }, { key: "all", label: "All" },
];
const PAGE_SIZE = 20;

export default function Page() {
  const [tab, setTab] = useState<Tab>("unread");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(nextOffset = 0, append = false) {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ status: tab, limit: String(PAGE_SIZE), offset: String(nextOffset) });
      if (search.trim()) params.set("search", search.trim());
      const resp = await api(`/notifications/center?${params}`);
      setItems((prev) => (append ? [...prev, ...resp.items] : resp.items));
      setTotal(resp.total);
      setHasMore(resp.has_more);
      setOffset(nextOffset);
    } catch (e: any) {
      if (String(e.message || "").includes("401")) { location.href = "/login"; return; }
      setError(formatApiError(e.message, "Couldn't load notifications"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(0, false); }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  function runSearch(e: React.FormEvent) { e.preventDefault(); load(0, false); }

  async function markRead(id: number) {
    await api(`/notifications/${id}/read`, { method: "POST" });
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
  }
  async function markUnread(id: number) {
    await api(`/notifications/${id}/unread`, { method: "POST" });
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: false } : n)));
  }
  async function archive(id: number) {
    await api(`/notifications/${id}/archive`, { method: "POST" });
    setItems((prev) => prev.filter((n) => n.id !== id));
    setTotal((t) => t - 1);
  }
  async function del(id: number) {
    await api(`/notifications/${id}`, { method: "DELETE" });
    setItems((prev) => prev.filter((n) => n.id !== id));
    setTotal((t) => t - 1);
  }
  async function markAllRead() {
    await api("/notifications/read-all", { method: "POST" });
    load(0, false);
  }

  return (
    <main className="container page">
      <div className="pagehead">
        <div>
          <span className="eyebrow">Notification center</span>
          <h1>Notifications</h1>
        </div>
        <div className="actions">
          <Link href="/notifications/preferences" className="btn secondary">Preferences</Link>
          <Link href="/subscriptions" className="btn secondary">Subscriptions</Link>
          {tab === "unread" && items.length > 0 && (
            <button className="btn secondary" onClick={markAllRead}>Mark all as read</button>
          )}
        </div>
      </div>

      <div className="filters">
        {TABS.map((t) => (
          <button key={t.key} className={`chip ${tab === t.key ? "chip-active" : ""}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <form className="search" onSubmit={runSearch} style={{ margin: "14px 0 6px" }}>
        <input className="field" placeholder="Search notifications…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <button className="btn secondary" type="submit">Search</button>
      </form>

      {error && <p className="error">{error}</p>}
      {loading && offset === 0 && <p className="muted">Loading…</p>}

      <div className="jobs" style={{ gridTemplateColumns: "1fr" }}>
        {items.map((n) => (
          <div className="card" key={n.id} style={{ opacity: n.read && tab !== "archived" ? 0.7 : 1 }}>
            <div className="row">
              <span className="pill">{TYPE_LABEL[n.notification_type] || n.notification_type}</span>
              {n.category && <span className="pill">{n.category}</span>}
              {!n.read && <span className="verified">New</span>}
            </div>
            <h2 style={{ fontSize: 18 }}>
              {PRIORITY_ICON[n.priority]} {n.title}
            </h2>
            {PRIORITY_LABEL[n.priority] && <p className="muted" style={{ fontSize: 12, margin: "0 0 4px" }}>{PRIORITY_LABEL[n.priority]}</p>}
            <p className="muted">{n.message}</p>
            <div className="row">
              <span className="muted" style={{ fontSize: 13 }}>{new Date(n.created_at).toLocaleString()}</span>
              <div className="actions">
                {n.action_url && <Link className="linkbtn" href={n.action_url}>View</Link>}
                {!n.action_url && n.job_id && <Link className="linkbtn" href={`/jobs/${n.job_id}`}>View recruitment</Link>}
                {!n.read && <button className="linkbtn" onClick={() => markRead(n.id)}>Mark as read</button>}
                {n.read && tab !== "archived" && <button className="linkbtn" onClick={() => markUnread(n.id)}>Mark as unread</button>}
                {tab !== "archived" && <button className="linkbtn" onClick={() => archive(n.id)}>Archive</button>}
                <button className="linkbtn danger" onClick={() => del(n.id)}>Delete</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {!loading && !items.length && (
        <div className="empty">{tab === "unread" ? "You're all caught up." : "No notifications yet."}</div>
      )}

      {hasMore && (
        <div style={{ textAlign: "center", marginTop: 24 }}>
          <button className="btn secondary" disabled={loading} onClick={() => load(offset + PAGE_SIZE, true)}>
            {loading ? "Loading…" : `Load more (${total - items.length} remaining)`}
          </button>
        </div>
      )}
    </main>
  );
}
