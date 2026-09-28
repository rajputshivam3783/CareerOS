"use client";
// V25.4 — AI Career Agent & Automation. Additive new route; reuses the
// api() helper and card/field/btn/chip/badge styling every other
// candidate page already uses (see frontend/src/app/career-copilot/page.tsx).
// Deliberately a separate page/route from /career-copilot (V20.3,
// unchanged): the Copilot is a pure grounded-chat advisor; the Agent
// additionally executes tools/actions behind a confirmation model — see
// docs/V25_4_AI_CAREER_AGENT.md.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Tab = "chat" | "actions" | "history" | "brief" | "preferences";
const TABS: { key: Tab; label: string }[] = [
  { key: "chat", label: "Chat" },
  { key: "actions", label: "Pending actions" },
  { key: "history", label: "History" },
  { key: "brief", label: "Career brief" },
  { key: "preferences", label: "Preferences" },
];

const SUGGESTED_PROMPTS = [
  "Find jobs matching my profile.",
  "What skills should I learn for backend development?",
  "Which applications need attention?",
  "Prepare me for my next interview.",
  "Show me my saved jobs.",
  "Summarize my career progress.",
];

type ChatMessage = { id: number | string; role: string; content: string; pending?: boolean };
type AgentAction = { id: number; action_type: string; risk_level: string; status: string; params: any; result: any; error: string | null };

export default function CareerAgentPage() {
  const [tab, setTab] = useState<Tab>("chat");
  const [err, setErr] = useState("");

  const [conversations, setConversations] = useState<any[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [lastFailedMessage, setLastFailedMessage] = useState<string | null>(null);
  const [activeAction, setActiveAction] = useState<AgentAction | null>(null);

  const [pendingActions, setPendingActions] = useState<AgentAction[] | null>(null);
  const [brief, setBrief] = useState<any>(null);
  const [prefs, setPrefs] = useState<any>(null);
  const [prefsMsg, setPrefsMsg] = useState("");

  async function loadConversations() {
    try { setConversations((await api("/career-agent/conversations")).conversations); } catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { loadConversations(); }, []);

  async function openConversation(id: number) {
    setActiveId(id);
    try {
      const data = await api(`/career-agent/conversations/${id}`);
      setMessages(data.messages);
    } catch (e: any) { setErr(e.message); }
  }

  async function newConversation() {
    try {
      const c = await api("/career-agent/conversations", { method: "POST", body: JSON.stringify({}) });
      setConversations((v) => [c, ...v]);
      setActiveId(c.id);
      setMessages([]);
      setActiveAction(null);
    } catch (e: any) { setErr(e.message); }
  }

  async function renameConversation(id: number) {
    const title = prompt("Conversation title:");
    if (!title) return;
    try {
      const updated = await api(`/career-agent/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ title }) });
      setConversations((v) => v.map((c) => (c.id === id ? updated : c)));
    } catch (e: any) { setErr(e.message); }
  }

  async function archiveConversation(id: number) {
    try {
      await api(`/career-agent/conversations/${id}/archive`, { method: "POST" });
      setConversations((v) => v.filter((c) => c.id !== id));
      if (activeId === id) { setActiveId(null); setMessages([]); }
    } catch (e: any) { setErr(e.message); }
  }

  async function deleteConversation(id: number) {
    if (!confirm("Delete this conversation? This can't be undone.")) return;
    try {
      await api(`/career-agent/conversations/${id}`, { method: "DELETE" });
      setConversations((v) => v.filter((c) => c.id !== id));
      if (activeId === id) { setActiveId(null); setMessages([]); }
    } catch (e: any) { setErr(e.message); }
  }

  async function sendMessage(text: string) {
    if (!text.trim()) return;
    let convId = activeId;
    if (!convId) {
      const c = await api("/career-agent/conversations", { method: "POST", body: JSON.stringify({}) });
      setConversations((v) => [c, ...v]);
      convId = c.id;
      setActiveId(c.id);
    }
    setSending(true); setErr(""); setLastFailedMessage(null); setActiveAction(null);
    setMessages((v) => [...v, { id: `pending-${Date.now()}`, role: "user", content: text }]);
    setDraft("");
    try {
      const r = await api(`/career-agent/conversations/${convId}/messages`, { method: "POST", body: JSON.stringify({ message: text }) });
      setMessages((v) => [...v, { id: r.message_id ?? `reply-${Date.now()}`, role: "assistant", content: r.reply }]);
      if (r.action && r.action.status === "PENDING_CONFIRMATION") setActiveAction(r.action);
      loadConversations();
    } catch (e: any) {
      setErr(e.message);
      setLastFailedMessage(text);
    } finally {
      setSending(false);
    }
  }

  async function loadPendingActions() {
    try { setPendingActions((await api("/career-agent/pending-actions")).pending_actions); } catch (e: any) { setErr(e.message); }
  }
  async function loadBrief() {
    try { setBrief(await api("/career-agent/brief")); } catch (e: any) { setErr(e.message); }
  }
  async function loadPreferences() {
    try { setPrefs(await api("/career-agent/preferences")); } catch (e: any) { setErr(e.message); }
  }

  useEffect(() => {
    if (tab === "actions") loadPendingActions();
    if (tab === "brief" && !brief) loadBrief();
    if (tab === "preferences") loadPreferences();
  }, [tab]);

  async function confirmAction(id: number) {
    try {
      const updated = await api(`/career-agent/actions/${id}/confirm`, { method: "POST" });
      setPendingActions((v) => (v || []).filter((a) => a.id !== id));
      if (activeAction?.id === id) setActiveAction(updated);
      if (activeId) openConversation(activeId);
    } catch (e: any) { setErr(e.message); }
  }

  async function rejectAction(id: number) {
    try {
      const updated = await api(`/career-agent/actions/${id}/reject`, { method: "POST" });
      setPendingActions((v) => (v || []).filter((a) => a.id !== id));
      if (activeAction?.id === id) setActiveAction(updated);
      if (activeId) openConversation(activeId);
    } catch (e: any) { setErr(e.message); }
  }

  async function savePreferences() {
    try {
      setPrefsMsg("");
      const saved = await api("/career-agent/preferences", { method: "PATCH", body: JSON.stringify(prefs) });
      setPrefs(saved);
      setPrefsMsg("Saved.");
    } catch (e: any) { setErr(e.message); }
  }

  return (
    <main className="container page">
      <span className="eyebrow">AI career agent</span>
      <h1>Career Agent</h1>
      <p className="muted">
        The Agent can search jobs, review your applications, plan follow-ups, and prep you for interviews —
        using your actual CareerOS data. It never submits an application or sends a message on its own:
        anything that changes your data or reaches outside CareerOS asks for confirmation first.
      </p>
      {err && <p className="error">{err}</p>}

      <div className="filters">
        {TABS.map((t) => (
          <button key={t.key} className={`chip ${tab === t.key ? "chip-active" : ""}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "chat" && (
        <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 16, marginTop: 18 }}>
          <div className="card">
            <button className="btn" style={{ width: "100%" }} onClick={newConversation}>+ New conversation</button>
            <div style={{ marginTop: 12 }}>
              {conversations.map((c) => (
                <div key={c.id} style={{ padding: "8px 4px", borderBottom: "1px solid var(--line)", cursor: "pointer", fontWeight: activeId === c.id ? 700 : 400 }}>
                  <div onClick={() => openConversation(c.id)}>{c.title || `Conversation #${c.id}`}</div>
                  <div style={{ fontSize: 11 }}>
                    <a onClick={() => renameConversation(c.id)} style={{ cursor: "pointer", marginRight: 8 }}>Rename</a>
                    <a onClick={() => archiveConversation(c.id)} style={{ cursor: "pointer", marginRight: 8 }}>Archive</a>
                    <a onClick={() => deleteConversation(c.id)} style={{ cursor: "pointer" }}>Delete</a>
                  </div>
                </div>
              ))}
              {!conversations.length && <p className="muted" style={{ fontSize: 13 }}>No conversations yet.</p>}
            </div>
          </div>

          <div className="card">
            <div style={{ minHeight: 300, maxHeight: 480, overflowY: "auto" }}>
              {!messages.length && (
                <div>
                  <p className="muted">Try asking:</p>
                  {SUGGESTED_PROMPTS.map((q) => (
                    <button key={q} className="chip" style={{ margin: 4 }} onClick={() => sendMessage(q)}>{q}</button>
                  ))}
                </div>
              )}
              {messages.map((m) => (
                <div key={m.id} style={{ margin: "10px 0", textAlign: m.role === "user" ? "right" : "left" }}>
                  <div className="card" style={{ display: "inline-block", padding: 10, maxWidth: "80%", background: m.role === "user" ? "var(--signal-wash)" : undefined }}>
                    {m.content}
                  </div>
                </div>
              ))}
              {sending && <p className="muted">Thinking...</p>}
            </div>

            {activeAction && activeAction.status === "PENDING_CONFIRMATION" && (
              <div className="card" style={{ marginTop: 8, padding: 10, borderColor: "var(--warn)" }}>
                <p style={{ fontSize: 13 }}>
                  <span className="badge">{activeAction.risk_level}</span>{" "}
                  Waiting for your confirmation: <b>{activeAction.action_type}</b>
                </p>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn" onClick={() => confirmAction(activeAction.id)}>Confirm</button>
                  <button className="btn" onClick={() => rejectAction(activeAction.id)}>Cancel</button>
                </div>
              </div>
            )}

            {lastFailedMessage && (
              <div className="card" style={{ marginTop: 8, padding: 10 }}>
                <p className="error" style={{ fontSize: 13 }}>That message didn't send.</p>
                <button className="btn" onClick={() => sendMessage(lastFailedMessage)}>Retry</button>
              </div>
            )}

            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <input
                className="field" style={{ flex: 1 }} value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") sendMessage(draft); }}
                placeholder="Ask about jobs, applications, interview prep, or your resume..."
              />
              <button className="btn" onClick={() => sendMessage(draft)} disabled={sending}>Send</button>
            </div>
          </div>
        </div>
      )}

      {tab === "actions" && (
        <div style={{ marginTop: 18 }}>
          <h2>Pending actions</h2>
          <p className="muted" style={{ fontSize: 13 }}>
            Nothing here runs until you approve it. WRITE actions change your CareerOS data; HIGH_RISK actions
            touch something outside CareerOS (an application link, a recruiter message) and are never
            submitted/sent automatically even after you confirm.
          </p>
          {(pendingActions || []).map((a) => (
            <div className="card" key={a.id} style={{ marginTop: 10 }}>
              <p><span className="badge">{a.risk_level}</span> <b>{a.action_type}</b></p>
              <p className="muted" style={{ fontSize: 12 }}>{JSON.stringify(a.params)}</p>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn" onClick={() => confirmAction(a.id)}>Confirm</button>
                <button className="btn" onClick={() => rejectAction(a.id)}>Cancel</button>
              </div>
            </div>
          ))}
          {pendingActions !== null && !pendingActions.length && <p className="muted">No actions waiting on you right now.</p>}
        </div>
      )}

      {tab === "history" && (
        <div style={{ marginTop: 18 }}>
          <h2>Conversation history</h2>
          {conversations.map((c) => (
            <div className="card" key={c.id} style={{ marginTop: 10, cursor: "pointer" }} onClick={() => { setTab("chat"); openConversation(c.id); }}>
              <b>{c.title || `Conversation #${c.id}`}</b>
              <p className="muted" style={{ fontSize: 12 }}>{c.message_count} messages · updated {new Date(c.updated_at).toLocaleString()}</p>
            </div>
          ))}
          {!conversations.length && <p className="muted">No conversations yet.</p>}
        </div>
      )}

      {tab === "brief" && brief && (
        <div className="card" style={{ marginTop: 18 }}>
          <h2>Career Brief</h2>
          <p>{brief.summary}</p>
          {brief.has_meaningful_update && (
            <>
              <h3>New relevant jobs</h3>
              <ul>{brief.new_relevant_jobs.map((j: any) => <li key={j.job_id}>{j.title} — {j.organization}</li>)}</ul>
              <h3>Upcoming deadlines</h3>
              <ul>{brief.upcoming_deadlines.map((d: any, i: number) => <li key={i}>{d.company} — {d.deadline} ({d.urgency})</li>)}</ul>
              <h3>Pending tasks</h3>
              <ul>{brief.pending_tasks.map((t: any) => <li key={t.id}>{t.title}{t.due_at ? ` (due ${t.due_at})` : ""}</li>)}</ul>
              <h3>Unread notifications</h3>
              <ul>{brief.unread_notifications.map((n: any) => <li key={n.id}>{n.title}</li>)}</ul>
            </>
          )}
        </div>
      )}

      {tab === "preferences" && prefs && (
        <div className="card" style={{ marginTop: 18, maxWidth: 480 }}>
          <h2>Proactive notifications</h2>
          <label style={{ display: "block", margin: "10px 0" }}>
            <input type="checkbox" checked={prefs.proactive_enabled} onChange={(e) => setPrefs({ ...prefs, proactive_enabled: e.target.checked })} />
            {" "}Enable proactive Career Agent notifications
          </label>
          <label style={{ display: "block", margin: "10px 0" }}>
            Frequency
            <select className="field" value={prefs.frequency} onChange={(e) => setPrefs({ ...prefs, frequency: e.target.value })}>
              <option value="instant">Instant</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
          </label>
          <label style={{ display: "block", margin: "10px 0" }}>
            Quiet hours start (0-23)
            <input className="field" type="number" min={0} max={23} value={prefs.quiet_hours_start ?? ""} onChange={(e) => setPrefs({ ...prefs, quiet_hours_start: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
          <label style={{ display: "block", margin: "10px 0" }}>
            Quiet hours end (0-23)
            <input className="field" type="number" min={0} max={23} value={prefs.quiet_hours_end ?? ""} onChange={(e) => setPrefs({ ...prefs, quiet_hours_end: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
          <button className="btn" onClick={savePreferences}>Save</button>
          {prefsMsg && <span className="muted" style={{ marginLeft: 8 }}>{prefsMsg}</span>}
        </div>
      )}
    </main>
  );
}
