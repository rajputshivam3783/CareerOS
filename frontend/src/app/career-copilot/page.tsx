"use client";
// V20.3 — AI Career Copilot. Additive new route; reuses the api()
// helper and card/field/btn styling every other candidate page
// already uses (see frontend/src/app/resume/intelligence/page.tsx).
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Tab = "chat" | "context" | "recommendations" | "roadmap" | "actions" | "preferences";
const TABS: { key: Tab; label: string }[] = [
  { key: "chat", label: "Chat" },
  { key: "context", label: "Career context" },
  { key: "recommendations", label: "Job suggestions" },
  { key: "roadmap", label: "Roadmap & skill gaps" },
  { key: "actions", label: "Action items" },
  { key: "preferences", label: "Preferences" },
];

const SUGGESTED_QUESTIONS = [
  "What jobs are suitable for me?",
  "What skills am I missing?",
  "How can I improve my resume?",
  "What should I learn next?",
  "Which saved jobs should I prioritize?",
  "How can I improve my chances?",
];

export default function CareerCopilotPage() {
  const [tab, setTab] = useState<Tab>("chat");
  const [err, setErr] = useState("");

  // Chat state
  const [conversations, setConversations] = useState<any[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [lastFailedMessage, setLastFailedMessage] = useState<string | null>(null);

  // Other tabs
  const [context, setContext] = useState<any>(null);
  const [recs, setRecs] = useState<any[] | null>(null);
  const [roadmapData, setRoadmapData] = useState<any>(null);
  const [items, setItems] = useState<any[] | null>(null);
  const [prefs, setPrefs] = useState<any>({});
  const [prefsMsg, setPrefsMsg] = useState("");

  async function loadConversations() {
    try {
      const r = await api("/career-copilot/conversations");
      setConversations(r.conversations);
      if (!activeId && r.conversations.length) setActiveId(r.conversations[0].id);
    } catch (e: any) { setErr(e.message); }
  }

  async function loadMessages(id: number) {
    try {
      const r = await api(`/career-copilot/conversations/${id}/messages`);
      setMessages(r.messages);
    } catch (e: any) { setErr(e.message); }
  }

  useEffect(() => { loadConversations(); }, []);
  useEffect(() => { if (activeId) loadMessages(activeId); }, [activeId]);

  async function newConversation() {
    try {
      const c = await api("/career-copilot/conversations", { method: "POST", body: JSON.stringify({}) });
      setConversations((v) => [c, ...v]);
      setActiveId(c.id);
      setMessages([]);
    } catch (e: any) { setErr(e.message); }
  }

  async function renameConversation(id: number) {
    const title = prompt("Rename conversation to:");
    if (!title) return;
    try {
      const c = await api(`/career-copilot/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ title }) });
      setConversations((v) => v.map((x) => (x.id === id ? c : x)));
    } catch (e: any) { setErr(e.message); }
  }

  async function deleteConversation(id: number) {
    if (!confirm("Delete this conversation permanently?")) return;
    try {
      await api(`/career-copilot/conversations/${id}`, { method: "DELETE" });
      setConversations((v) => v.filter((x) => x.id !== id));
      if (activeId === id) { setActiveId(null); setMessages([]); }
    } catch (e: any) { setErr(e.message); }
  }

  async function clearConversation(id: number) {
    if (!confirm("Clear all messages in this conversation?")) return;
    try {
      await api(`/career-copilot/conversations/${id}/clear`, { method: "POST" });
      setMessages([]);
    } catch (e: any) { setErr(e.message); }
  }

  async function sendMessage(text: string) {
    if (!text.trim()) return;
    let convId = activeId;
    if (!convId) {
      const c = await api("/career-copilot/conversations", { method: "POST", body: JSON.stringify({}) });
      setConversations((v) => [c, ...v]);
      convId = c.id;
      setActiveId(c.id);
    }
    setSending(true); setErr(""); setLastFailedMessage(null);
    setMessages((v) => [...v, { id: `pending-${Date.now()}`, role: "user", content: text, created_at: new Date().toISOString() }]);
    setDraft("");
    try {
      const r = await api(`/career-copilot/conversations/${convId}/messages`, { method: "POST", body: JSON.stringify({ message: text }) });
      setMessages((v) => [...v, r.reply]);
      loadConversations();
    } catch (e: any) {
      setErr(e.message);
      setLastFailedMessage(text);
    } finally {
      setSending(false);
    }
  }

  async function loadContext() {
    try { setContext(await api("/career-copilot/context")); } catch (e: any) { setErr(e.message); }
  }
  async function loadRecommendations() {
    try { setRecs((await api("/career-copilot/recommendations")).recommendations); } catch (e: any) { setErr(e.message); }
  }
  async function loadRoadmap() {
    try { setRoadmapData(await api("/career-copilot/roadmap")); } catch (e: any) { setErr(e.message); }
  }
  async function loadActionItems() {
    try { setItems((await api("/career-copilot/action-plan")).items); } catch (e: any) { setErr(e.message); }
  }
  async function loadPreferences() {
    try { setPrefs(await api("/career-copilot/preferences")); } catch (e: any) { setErr(e.message); }
  }

  useEffect(() => {
    if (tab === "context" && !context) loadContext();
    if (tab === "recommendations" && recs === null) loadRecommendations();
    if (tab === "roadmap" && !roadmapData) loadRoadmap();
    if (tab === "actions" && items === null) loadActionItems();
    if (tab === "preferences") loadPreferences();
  }, [tab]);

  async function updateItemStatus(id: number, status: string) {
    try {
      const updated = await api(`/career-copilot/action-plan/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
      setItems((v) => (v || []).map((it) => (it.id === id ? updated : it)));
    } catch (e: any) { setErr(e.message); }
  }

  async function savePreferences() {
    try {
      setPrefsMsg("");
      const saved = await api("/career-copilot/preferences", { method: "PUT", body: JSON.stringify(prefs) });
      setPrefs(saved);
      setPrefsMsg("Saved.");
    } catch (e: any) { setErr(e.message); }
  }

  const buckets = ["today", "this_week", "this_month", "next_3_months"];
  const bucketLabels: Record<string, string> = { today: "Today", this_week: "This week", this_month: "This month", next_3_months: "Next 3 months" };

  return (
    <main className="container page">
      <span className="eyebrow">AI career copilot</span>
      <h1>Career Copilot</h1>
      <p className="muted">
        Grounded in your actual CareerOS data — profile, resume, saved jobs, applications, and preferences.
        When something isn't on file, the Copilot says so rather than guessing.
      </p>
      {err && <p className="error">{err}</p>}

      <div className="filters">
        {TABS.map((t) => <button key={t.key} className={`chip ${tab === t.key ? "chip-active" : ""}`} onClick={() => setTab(t.key)}>{t.label}</button>)}
      </div>

      {tab === "chat" && (
        <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 16, marginTop: 18 }}>
          <div className="card">
            <button className="btn" style={{ width: "100%" }} onClick={newConversation}>+ New conversation</button>
            <div style={{ marginTop: 12 }}>
              {conversations.map((c) => (
                <div key={c.id} style={{ padding: "8px 4px", borderBottom: "1px solid var(--line)", cursor: "pointer", fontWeight: activeId === c.id ? 700 : 400 }}>
                  <div onClick={() => setActiveId(c.id)}>{c.title || `Conversation #${c.id}`}</div>
                  <div style={{ fontSize: 11 }}>
                    <a onClick={() => renameConversation(c.id)} style={{ cursor: "pointer", marginRight: 8 }}>Rename</a>
                    <a onClick={() => clearConversation(c.id)} style={{ cursor: "pointer", marginRight: 8 }}>Clear</a>
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
                  {SUGGESTED_QUESTIONS.map((q) => (
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
                placeholder="Ask about jobs, skills, your resume, or a government exam..."
              />
              <button className="btn" onClick={() => sendMessage(draft)} disabled={sending}>Send</button>
            </div>
          </div>
        </div>
      )}

      {tab === "context" && context && (
        <div className="card" style={{ marginTop: 18 }}>
          <h2>What the Copilot knows about you</h2>
          <p><b>Profile:</b> {context.profile ? JSON.stringify(context.profile) : "Not set"}</p>
          <p><b>Preferences:</b> {context.preferences ? JSON.stringify(context.preferences) : "Not set"}</p>
          <p><b>Resume:</b> {context.resume_summary ? `${context.resume_summary.technical_skills.length} skills detected, score ${context.resume_summary.overall_score}/100` : "Not uploaded"}</p>
          <p><b>Saved jobs:</b> {context.saved_jobs.length}</p>
          <p><b>Applications:</b> {context.applications.length}</p>
          <p><b>Upcoming deadlines (14 days):</b> {context.upcoming_deadlines.length}</p>
          <h3 style={{ marginTop: 12 }}>Not yet known</h3>
          <ul className="muted" style={{ fontSize: 13 }}>{context.unknown_fields.map((f: string, i: number) => <li key={i}>{f}</li>)}</ul>
        </div>
      )}

      {tab === "recommendations" && (
        <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
          {(recs || []).map((r: any) => (
            <div className="card" key={r.job_id}>
              <b>{r.title}</b> — {r.organization} <span className="badge badge-active">{r.score}% match</span>
              <p className="muted" style={{ fontSize: 13 }}>{r.explanation}</p>
              <p className="muted" style={{ fontSize: 13 }}>Matched skills: {r.matched_skills.join(", ") || "none"}</p>
            </div>
          ))}
          {recs !== null && !recs.length && <div className="empty">No recommendations yet — complete your profile or upload a resume.</div>}
        </div>
      )}

      {tab === "roadmap" && roadmapData && (
        <div className="card" style={{ marginTop: 18 }}>
          <h2>Target role: {roadmapData.target_role}</h2>
          <p><b>Current skills:</b> {(roadmapData.current_position.current_skills || []).join(", ") || "None detected"}</p>
          <h3 style={{ marginTop: 12 }}>Skill gaps</h3>
          <p className="muted" style={{ fontSize: 13 }}>{JSON.stringify(roadmapData.skill_gaps.missing_skills || roadmapData.skill_gaps.learn || [])}</p>
          <h3 style={{ marginTop: 12 }}>Learning priorities</h3>
          <ul>{roadmapData.learning_priorities.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul>
          <h3 style={{ marginTop: 12 }}>Suggested projects</h3>
          <ul>{roadmapData.projects.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul>
          <h3 style={{ marginTop: 12 }}>Interview preparation</h3>
          <ul>{roadmapData.interview_preparation.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul>
        </div>
      )}

      {tab === "actions" && (
        <div style={{ marginTop: 18 }}>
          {buckets.map((b) => (
            <div key={b} style={{ marginBottom: 16 }}>
              <h3>{bucketLabels[b]}</h3>
              {(items || []).filter((it) => it.bucket === b).map((it) => (
                <div className="card row" key={it.id} style={{ opacity: it.status === "done" ? 0.5 : 1 }}>
                  <div>
                    <span className={`badge badge-${it.priority === "high" ? "paused" : it.priority === "medium" ? "open" : "active"}`}>{it.priority}</span>
                    <b style={{ marginLeft: 8 }}>{it.title}</b>
                    <p className="muted" style={{ fontSize: 13 }}>{it.reason}</p>
                    {it.status === "pending" && (
                      <>
                        <button className="btn" onClick={() => updateItemStatus(it.id, "done")}>Mark done</button>
                        <button className="btn" onClick={() => updateItemStatus(it.id, "dismissed")} style={{ marginLeft: 8 }}>Dismiss</button>
                      </>
                    )}
                  </div>
                </div>
              ))}
              {items !== null && !items.filter((it) => it.bucket === b).length && <p className="muted" style={{ fontSize: 13 }}>Nothing here.</p>}
            </div>
          ))}
        </div>
      )}

      {tab === "preferences" && (
        <div className="card form" style={{ marginTop: 18 }}>
          <h2>Career preferences</h2>
          <p className="muted">Self-reported — the Copilot never infers these on its own.</p>
          {[
            ["target_role", "Target role"], ["preferred_industry", "Preferred industry"],
            ["preferred_location", "Preferred location"], ["preferred_work_mode", "Preferred work mode (remote/hybrid/onsite)"],
            ["experience_level", "Experience level"], ["target_companies", "Target companies"],
            ["salary_expectation", "Salary expectation"], ["preferred_skills", "Preferred skills"],
            ["learning_goals", "Learning goals"], ["career_goal", "Career goal"],
          ].map(([key, label]) => (
            <label className="field-label" key={key}>{label}
              <input className="field" value={prefs[key] || ""} onChange={(e) => setPrefs((v: any) => ({ ...v, [key]: e.target.value }))} />
            </label>
          ))}
          <div className="actions"><button className="btn" onClick={savePreferences}>Save</button></div>
          {prefsMsg && <p className="muted">{prefsMsg}</p>}
        </div>
      )}
    </main>
  );
}
