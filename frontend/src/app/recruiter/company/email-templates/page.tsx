"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Template = {
  id: number;
  template_type: string;
  label: string;
  subject: string;
  body: string;
  is_custom: boolean;
  updated_at: string;
};

export default function Page() {
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [activeType, setActiveType] = useState<string>("application_received");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [variables, setVariables] = useState<string[]>([]);
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");
  const bodyRef = useRef<HTMLTextAreaElement | null>(null);

  async function loadAll() {
    try {
      setErr("");
      const list = await api("/recruiter/company/email-templates");
      setTemplates(list);
      const meta = await api("/recruiter/company/email-templates-meta/variables");
      setVariables(meta.variables || []);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  useEffect(() => {
    if (!templates) return;
    const active = templates.find((t) => t.template_type === activeType);
    if (active) {
      setSubject(active.subject);
      setBody(active.body);
    }
    setPreview(null);
    setNotice("");
  }, [activeType, templates]);

  function insertVariable(name: string) {
    const token = `{{${name}}}`;
    const el = bodyRef.current;
    if (!el) {
      setBody((b) => b + token);
      return;
    }
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? body.length;
    const next = body.slice(0, start) + token + body.slice(end);
    setBody(next);
    requestAnimationFrame(() => {
      el.focus();
      const pos = start + token.length;
      el.setSelectionRange(pos, pos);
    });
  }

  async function save() {
    setSaving(true);
    setErr("");
    setNotice("");
    try {
      const updated = await api(`/recruiter/company/email-templates/${activeType}`, {
        method: "PUT",
        body: JSON.stringify({ subject, body }),
      });
      setTemplates((prev) => (prev ? prev.map((t) => (t.template_type === activeType ? updated : t)) : prev));
      setNotice("Saved.");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!window.confirm("Reset this template to the default wording? Your edits will be lost.")) return;
    setResetting(true);
    setErr("");
    setNotice("");
    try {
      const updated = await api(`/recruiter/company/email-templates/${activeType}/reset`, { method: "POST" });
      setTemplates((prev) => (prev ? prev.map((t) => (t.template_type === activeType ? updated : t)) : prev));
      setSubject(updated.subject);
      setBody(updated.body);
      setPreview(null);
      setNotice("Reset to default.");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setResetting(false);
    }
  }

  async function runPreview() {
    setPreviewing(true);
    setErr("");
    try {
      const rendered = await api(`/recruiter/company/email-templates/${activeType}/preview`, {
        method: "POST",
        body: JSON.stringify({ subject, body }),
      });
      setPreview(rendered);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setPreviewing(false);
    }
  }

  if (err && !templates) return <main className="container page"><p className="error">{err}</p></main>;
  if (!templates) return <main className="container page">Loading…</main>;

  const active = templates.find((t) => t.template_type === activeType);

  return (
    <main className="container page">
      <span className="eyebrow">Company · email templates</span>
      <div className="pagehead">
        <div>
          <h1>Email templates</h1>
          <p className="muted">
            Customize the wording used at each stage of your hiring pipeline. Use the variable buttons to insert
            placeholders like candidate name or job title — they're filled in automatically wherever a template is used.
          </p>
        </div>
        <a className="btn secondary" href="/recruiter/company">Company profile</a>
      </div>

      {err && <p className="error">{err}</p>}
      {notice && <p className="muted">{notice}</p>}

      <div className="filters">
        {templates.map((t) => (
          <button
            key={t.template_type}
            className={t.template_type === activeType ? "chip chip-active" : "chip"}
            onClick={() => setActiveType(t.template_type)}
          >
            {t.label}
            {t.is_custom ? " •" : ""}
          </button>
        ))}
      </div>

      <div className="detailgrid section">
        <div className="card form">
          <div className="row">
            <h2>{active?.label}</h2>
            <span className="pill">{active?.is_custom ? "Customized" : "Default"}</span>
          </div>

          <label className="field-label">
            Subject
            <input className="field" value={subject} onChange={(e) => setSubject(e.target.value)} />
          </label>

          <label className="field-label">
            Body
            <textarea
              ref={bodyRef}
              className="field"
              rows={12}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </label>

          <div className="field-label">
            Insert variable
            <div className="filters" style={{ margin: 0 }}>
              {variables.map((v) => (
                <button key={v} type="button" className="chip" onClick={() => insertVariable(v)}>
                  {`{{${v}}}`}
                </button>
              ))}
            </div>
          </div>

          <div className="actions">
            <button className="btn" disabled={saving} onClick={save}>
              {saving ? "Saving…" : "Save template"}
            </button>
            <button className="btn secondary" disabled={previewing} onClick={runPreview}>
              {previewing ? "Rendering…" : "Preview with sample data"}
            </button>
            <button className="btn secondary danger" disabled={resetting} onClick={reset}>
              {resetting ? "Resetting…" : "Reset to default"}
            </button>
          </div>
        </div>

        <div className="card stickycard">
          <h2>Preview</h2>
          {!preview && <p className="muted">Click "Preview with sample data" to see how this renders for a candidate.</p>}
          {preview && (
            <div>
              <p className="field-label">Subject</p>
              <p className="strong">{preview.subject}</p>
              <p className="field-label section">Body</p>
              <div className="result" style={{ background: "var(--surface)", color: "var(--ink)", border: "1px solid var(--line)" }}>
                {preview.body}
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
