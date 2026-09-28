"use client";
// V20.1 — AI Infrastructure admin console. Same X-Admin-Key-or-session
// pattern as src/app/admin/notifications/page.tsx (additive new route,
// doesn't touch that page or any other admin page).
import { useEffect, useState } from "react";
import { API, formatApiError, token } from "@/lib/api";

type Tab = "overview" | "providers" | "usage" | "logs" | "prompts" | "config";
const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "providers", label: "Providers" },
  { key: "usage", label: "Usage" },
  { key: "logs", label: "Logs" },
  { key: "prompts", label: "Prompt registry" },
  { key: "config", label: "Configuration" },
];

export default function AiAdminPage() {
  const [key, setKey] = useState("");
  const [hasSession, setHasSession] = useState(false);
  const [tab, setTab] = useState<Tab>("overview");
  const [msg, setMsg] = useState("");

  const [health, setHealth] = useState<any>(null);
  const [providers, setProviders] = useState<any[]>([]);
  const [usage, setUsage] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [prompts, setPrompts] = useState<any[]>([]);
  const [config, setConfig] = useState<any>(null);

  const [newPrompt, setNewPrompt] = useState({ key: "", template: "", variables: "", description: "" });

  useEffect(() => { setHasSession(!!token()); }, []);

  async function call(path: string, method = "GET", body?: any) {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const t = token(); if (t) headers["Authorization"] = `Bearer ${t}`;
    if (key) headers["X-Admin-Key"] = key;
    const r = await fetch(`${API}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let j: any = null; try { j = await r.json(); } catch {}
    if (!r.ok) throw new Error(formatApiError(j, "AI admin request failed"));
    return j;
  }

  async function loadHealth() { setHealth(await call("/ai/health")); }
  async function loadProviders() { setProviders((await call("/ai/providers")).providers); }
  async function loadUsage() { setUsage(await call("/ai/usage?since_hours=24")); }
  async function loadLogs() { setLogs((await call("/ai/usage/logs?limit=50")).logs); }
  async function loadPrompts() { setPrompts((await call("/ai/prompts")).templates); }
  async function loadConfig() { setConfig(await call("/ai/config")); }

  async function openWorkspace() {
    try {
      setMsg("");
      await Promise.all([loadHealth(), loadProviders(), loadUsage(), loadLogs(), loadPrompts(), loadConfig()]);
    } catch (e: any) { setMsg(e.message); }
  }

  async function createPrompt() {
    try {
      const variables = newPrompt.variables.split(",").map((v) => v.trim()).filter(Boolean);
      await call("/ai/prompts", "POST", {
        key: newPrompt.key, template: newPrompt.template, variables, description: newPrompt.description || null,
      });
      setNewPrompt({ key: "", template: "", variables: "", description: "" });
      loadPrompts();
      setMsg("Prompt template saved.");
    } catch (e: any) { setMsg(e.message); }
  }

  return (
    <main className="container page">
      <span className="eyebrow">AI infrastructure & LLM framework — admin</span>
      <h1>AI infrastructure</h1>
      <p className="muted">
        Provider abstraction, prompt registry, conversation memory, and usage observability for the
        reusable AI foundation layer. This dashboard does not configure Resume AI, Interview AI, or Career
        Copilot — those are later-version features built on top of this layer.
      </p>

      <div className="card form">
        {hasSession
          ? <p className="muted">Signed in as admin — using your session automatically.</p>
          : <label className="field-label">Admin key
              <input className="field" type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="X-Admin-Key" />
            </label>}
        <div className="actions">
          <button className="btn" onClick={openWorkspace}>Load workspace</button>
        </div>
        {msg && <p className="muted">{msg}</p>}
      </div>

      <div className="filters">
        {TABS.map((t) => <button key={t.key} className={`chip ${tab === t.key ? "chip-active" : ""}`} onClick={() => setTab(t.key)}>{t.label}</button>)}
      </div>

      {tab === "overview" && health && (
        <div className="metrics" style={{ marginTop: 18 }}>
          <div className="metric"><b>{health.status}</b><span>Overall status</span></div>
          <div className="metric"><b>{health.default_provider}</b><span>Default provider</span></div>
          <div className="metric"><b>{health.fallback_provider || "none"}</b><span>Fallback provider</span></div>
          <div className="metric"><b>{health.configured_providers.length}</b><span>Providers configured</span></div>
          <div className="metric"><b>{Math.round(health.uptime_seconds)}s</b><span>Process uptime</span></div>
        </div>
      )}
      {tab === "overview" && health && Object.keys(health.live_health).length > 0 && (
        <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
          <h2>Live provider health (this process)</h2>
          {Object.entries(health.live_health).map(([name, h]: any) => (
            <div className="card row" key={name}>
              <div>
                <span className="strong">{name}</span>
                <span className={`badge badge-${h.status === "healthy" ? "active" : "open"}`} style={{ marginLeft: 8 }}>{h.status}</span>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  {h.recent_calls} recent call(s) · {Math.round(h.recent_success_rate * 100)}% success · {h.recent_avg_latency_ms}ms avg latency
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {tab === "overview" && !health && <div className="empty">Load the workspace to see status.</div>}

      {tab === "providers" && (
        <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
          {providers.map((p) => (
            <div className="card row" key={p.name}>
              <div>
                <span className="pill">{p.name}</span>
                <span className={`badge badge-${p.configured ? "active" : "paused"}`} style={{ marginLeft: 8 }}>
                  {p.configured ? "configured" : "not configured"}
                </span>
                {p.is_default && <span className="badge badge-active" style={{ marginLeft: 8 }}>default</span>}
                {p.is_fallback && <span className="badge badge-open" style={{ marginLeft: 8 }}>fallback</span>}
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  capabilities: {p.capabilities.length ? p.capabilities.join(", ") : "none"}
                </div>
              </div>
            </div>
          ))}
          {!providers.length && <div className="empty">Load the workspace to see providers.</div>}
        </div>
      )}

      {tab === "usage" && usage && (
        <>
          <div className="metrics" style={{ marginTop: 18 }}>
            <div className="metric"><b>{usage.total_calls}</b><span>Total calls ({usage.since_hours}h)</span></div>
            <div className="metric"><b>{usage.success_count}</b><span>Successful</span></div>
            <div className="metric"><b>{usage.failure_count}</b><span>Failed</span></div>
            <div className="metric"><b>{usage.success_rate != null ? `${Math.round(usage.success_rate * 100)}%` : "—"}</b><span>Success rate</span></div>
          </div>
          <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
            {Object.entries(usage.by_provider || {}).map(([name, p]: any) => (
              <div className="card" key={name}>
                <span className="pill">{name}</span>
                <p className="muted" style={{ marginTop: 8 }}>
                  {p.total_calls} call(s) · {p.total_tokens} tokens · ${p.total_cost_usd.toFixed(4)} estimated
                </p>
                {Object.entries(p.by_service || {}).map(([svc, s]: any) => (
                  <div key={svc} className="muted" style={{ fontSize: 13 }}>
                    {svc}: {s.calls} call(s), {s.avg_latency_ms}ms avg latency, ${s.cost_usd.toFixed(4)}
                  </div>
                ))}
              </div>
            ))}
            {!Object.keys(usage.by_provider || {}).length && <div className="empty">No AI usage recorded yet.</div>}
          </div>
        </>
      )}
      {tab === "usage" && !usage && <div className="empty">Load the workspace to see usage.</div>}

      {tab === "logs" && (
        <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
          {logs.map((row) => (
            <div className="card row" key={row.id}>
              <div>
                <span className="pill">{row.service}</span>
                <span className={`badge badge-${row.success ? "active" : "open"}`} style={{ marginLeft: 8 }}>
                  {row.success ? "success" : "failed"}
                </span>
                {row.used_fallback && <span className="badge badge-paused" style={{ marginLeft: 8 }}>fallback used</span>}
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  {row.provider} {row.model ? `(${row.model})` : ""} · {row.operation || "—"} · {Math.round(row.latency_ms)}ms ·
                  {" "}{row.prompt_tokens + row.completion_tokens} tokens · ${row.cost_estimate_usd.toFixed(4)}
                </div>
                {row.error && <div className="error" style={{ fontSize: 13 }}>{row.error}</div>}
                <span className="muted" style={{ fontSize: 12 }}>{new Date(row.created_at).toLocaleString()}</span>
              </div>
            </div>
          ))}
          {!logs.length && <div className="empty">No AI calls logged yet.</div>}
        </div>
      )}

      {tab === "prompts" && (
        <>
          <div className="card form" style={{ marginTop: 18 }}>
            <h2>Register a new prompt version</h2>
            <label className="field-label">Key
              <input className="field" value={newPrompt.key} onChange={(e) => setNewPrompt({ ...newPrompt, key: e.target.value })} placeholder="e.g. resume_ai.rewrite_bullet" />
            </label>
            <label className="field-label">Template
              <textarea className="field" rows={4} value={newPrompt.template} onChange={(e) => setNewPrompt({ ...newPrompt, template: e.target.value })} placeholder="Use {variable} placeholders" />
            </label>
            <label className="field-label">Variables (comma-separated)
              <input className="field" value={newPrompt.variables} onChange={(e) => setNewPrompt({ ...newPrompt, variables: e.target.value })} placeholder="name, role" />
            </label>
            <label className="field-label">Description
              <input className="field" value={newPrompt.description} onChange={(e) => setNewPrompt({ ...newPrompt, description: e.target.value })} />
            </label>
            <div className="actions">
              <button className="btn" onClick={createPrompt}>Save new version</button>
            </div>
          </div>
          <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
            {prompts.map((t) => (
              <div className="card" key={t.id}>
                <span className="pill">{t.key}</span>
                <span className="muted" style={{ marginLeft: 8 }}>v{t.version}</span>
                <span className={`badge badge-${t.active ? "active" : "paused"}`} style={{ marginLeft: 8 }}>{t.active ? "active" : "superseded"}</span>
                {t.description && <p className="muted" style={{ marginTop: 8 }}>{t.description}</p>}
                <p style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>{t.template}</p>
              </div>
            ))}
            {!prompts.length && <div className="empty">No prompt templates loaded yet.</div>}
          </div>
        </>
      )}

      {tab === "config" && config && (
        <div className="card" style={{ marginTop: 18 }}>
          <h2>Active configuration</h2>
          <p className="muted" style={{ marginBottom: 12 }}>Read-only — set via environment variables. API keys are never returned here.</p>
          <table>
            <tbody>
              {Object.entries(config).filter(([k]) => k !== "provider_models").map(([k, v]: any) => (
                <tr key={k}><td className="muted">{k}</td><td>{String(v)}</td></tr>
              ))}
              {config.provider_models && Object.entries(config.provider_models).map(([name, model]: any) => (
                <tr key={name}><td className="muted">model — {name}</td><td>{model}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "config" && !config && <div className="empty">Load the workspace to see configuration.</div>}
    </main>
  );
}
