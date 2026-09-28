"use client";
// V20.5 — AI Learning & Skill Intelligence admin console. Same
// X-Admin-Key pattern as src/app/admin/ai/page.tsx (additive new
// route, doesn't touch that page or any other admin page). Covers the
// admin-only surfaces: catalog management (skills/aliases/
// relationships/reseed) and content authoring (resources,
// assessments/questions).
import { useEffect, useState } from "react";
import { API, formatApiError, token } from "@/lib/api";

type Tab = "skills" | "resources" | "assessments";
const TABS: { key: Tab; label: string }[] = [
  { key: "skills", label: "Skill Catalog" },
  { key: "resources", label: "Resources" },
  { key: "assessments", label: "Assessments" },
];

export default function LearningAdminPage() {
  const [key, setKey] = useState("");
  const [hasSession, setHasSession] = useState(false);
  const [tab, setTab] = useState<Tab>("skills");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const [skills, setSkills] = useState<any[]>([]);
  const [newSkill, setNewSkill] = useState({ canonical_name: "", display_name: "", category: "technical", subcategory: "", difficulty: "beginner", aliases: "" });
  const [aliasTarget, setAliasTarget] = useState<{ id: number; alias: string }>({ id: 0, alias: "" });
  const [relTarget, setRelTarget] = useState<{ id: number; to: string; type: string }>({ id: 0, to: "", type: "related" });

  const [resources, setResources] = useState<any[]>([]);
  const [newResource, setNewResource] = useState({ skill_canonical_name: "", title: "", provider: "", url: "", resource_type: "course", difficulty: "beginner", status: "draft", is_verified: false });

  const [assessments, setAssessments] = useState<any[]>([]);
  const [newAssessment, setNewAssessment] = useState({ skill_canonical_name: "", title: "", status: "draft" });
  const [newQuestion, setNewQuestion] = useState({ assessment_id: "", prompt: "", options: "", correct_option: "0", topic: "" });

  useEffect(() => { setHasSession(!!token()); }, []);

  async function call(path: string, method = "GET", body?: any) {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const t = token(); if (t) headers["Authorization"] = `Bearer ${t}`;
    if (key) headers["X-Admin-Key"] = key;
    const r = await fetch(`${API}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let j: any = null; try { j = await r.json(); } catch {}
    if (!r.ok) throw new Error(formatApiError(j, "Learning admin request failed"));
    return j;
  }

  async function loadSkills() { setErr(""); try { setSkills(await call("/admin/skills")); } catch (e: any) { setErr(e.message); } }
  async function loadResources() { setErr(""); try { setResources(await call("/admin/resources")); } catch (e: any) { setErr(e.message); } }
  async function loadAssessments() { setErr(""); try { /* admin list endpoint reuses candidate list without the published filter isn't exposed; show what we've created this session */ } catch (e: any) { setErr(e.message); } }

  useEffect(() => { if (tab === "skills") loadSkills(); if (tab === "resources") loadResources(); }, [tab]);

  async function createSkill() {
    setErr(""); setMsg("");
    try {
      const body: any = { ...newSkill, aliases: newSkill.aliases.split(",").map(a => a.trim()).filter(Boolean) };
      await call("/admin/skills", "POST", body);
      setMsg(`Created skill "${newSkill.display_name}"`);
      setNewSkill({ canonical_name: "", display_name: "", category: "technical", subcategory: "", difficulty: "beginner", aliases: "" });
      loadSkills();
    } catch (e: any) { setErr(e.message); }
  }

  async function addAlias() {
    setErr(""); setMsg("");
    try { await call(`/admin/skills/${aliasTarget.id}/aliases`, "POST", { alias: aliasTarget.alias }); setMsg("Alias added"); setAliasTarget({ id: 0, alias: "" }); loadSkills(); }
    catch (e: any) { setErr(e.message); }
  }

  async function addRelationship() {
    setErr(""); setMsg("");
    try { await call(`/admin/skills/${relTarget.id}/relationships`, "POST", { to_canonical_name: relTarget.to, relationship_type: relTarget.type }); setMsg("Relationship added"); setRelTarget({ id: 0, to: "", type: "related" }); }
    catch (e: any) { setErr(e.message); }
  }

  async function reseed() {
    setErr(""); setMsg("");
    try { const r = await call("/admin/skills/seed", "POST"); setMsg(`Re-seeded: ${r.skills_created} skills, ${r.aliases_created} aliases, ${r.relationships_created} relationships added.`); loadSkills(); }
    catch (e: any) { setErr(e.message); }
  }

  async function createResource() {
    setErr(""); setMsg("");
    try { await call("/admin/resources", "POST", newResource); setMsg(`Created resource "${newResource.title}"`); setNewResource({ skill_canonical_name: "", title: "", provider: "", url: "", resource_type: "course", difficulty: "beginner", status: "draft", is_verified: false }); loadResources(); }
    catch (e: any) { setErr(e.message); }
  }

  async function toggleResourceVerified(r: any) {
    setErr(""); setMsg("");
    try { await call(`/admin/resources/${r.id}`, "PUT", { is_verified: !r.is_verified, status: !r.is_verified ? "published" : r.status }); loadResources(); }
    catch (e: any) { setErr(e.message); }
  }

  async function createAssessment() {
    setErr(""); setMsg("");
    try {
      const a = await call("/admin/assessments", "POST", newAssessment);
      setMsg(`Created assessment "${a.title}" (id ${a.id}) — add questions below using this id.`);
      setAssessments([a, ...assessments]);
      setNewQuestion({ ...newQuestion, assessment_id: String(a.id) });
      setNewAssessment({ skill_canonical_name: "", title: "", status: "draft" });
    } catch (e: any) { setErr(e.message); }
  }

  async function addQuestion() {
    setErr(""); setMsg("");
    try {
      const options = newQuestion.options.split(",").map(o => o.trim()).filter(Boolean);
      await call(`/admin/assessments/${newQuestion.assessment_id}/questions`, "POST", {
        prompt: newQuestion.prompt, options, correct_option: Number(newQuestion.correct_option), topic: newQuestion.topic,
      });
      setMsg("Question added");
      setNewQuestion({ ...newQuestion, prompt: "", options: "", topic: "" });
    } catch (e: any) { setErr(e.message); }
  }

  return (
    <main id="main" className="page">
      <div className="container">
        <h1>Learning &amp; Skill Intelligence — Admin</h1>
        <p className="muted">Manage the canonical skill catalog, learning resources, and assessment content. Requires the admin key (or an admin session).</p>

        {!hasSession && (
          <div className="form narrow">
            <label className="field-label">Admin key
              <input className="field" type="password" value={key} onChange={e => setKey(e.target.value)} placeholder="X-Admin-Key" />
            </label>
          </div>
        )}

        <div className="filters">
          {TABS.map(t => <button key={t.key} className={`chip ${tab === t.key ? "chip-active" : ""}`} onClick={() => setTab(t.key)}>{t.label}</button>)}
        </div>

        {msg && <p className="muted">{msg}</p>}
        {err && <p className="error">{err}</p>}

        {tab === "skills" && (
          <div className="grid2" style={{ marginTop: 18 }}>
            <div className="card">
              <h2>Add a skill</h2>
              <div className="form">
                <input className="field" placeholder="canonical_name (e.g. rust)" value={newSkill.canonical_name} onChange={e => setNewSkill({ ...newSkill, canonical_name: e.target.value })} />
                <input className="field" placeholder="display_name (e.g. Rust)" value={newSkill.display_name} onChange={e => setNewSkill({ ...newSkill, display_name: e.target.value })} />
                <select className="field" value={newSkill.category} onChange={e => setNewSkill({ ...newSkill, category: e.target.value })}>
                  <option value="technical">technical</option><option value="soft">soft</option>
                </select>
                <input className="field" placeholder="subcategory (e.g. programming_language)" value={newSkill.subcategory} onChange={e => setNewSkill({ ...newSkill, subcategory: e.target.value })} />
                <select className="field" value={newSkill.difficulty} onChange={e => setNewSkill({ ...newSkill, difficulty: e.target.value })}>
                  <option>beginner</option><option>intermediate</option><option>advanced</option><option>expert</option>
                </select>
                <input className="field" placeholder="aliases, comma-separated" value={newSkill.aliases} onChange={e => setNewSkill({ ...newSkill, aliases: e.target.value })} />
                <button className="btn" onClick={createSkill}>Create skill</button>
              </div>
              <h2 style={{ marginTop: 24 }}>Add alias</h2>
              <div className="form">
                <input className="field" placeholder="skill id" value={aliasTarget.id || ""} onChange={e => setAliasTarget({ ...aliasTarget, id: Number(e.target.value) })} />
                <input className="field" placeholder="new alias" value={aliasTarget.alias} onChange={e => setAliasTarget({ ...aliasTarget, alias: e.target.value })} />
                <button className="btn secondary" onClick={addAlias}>Add alias</button>
              </div>
              <h2 style={{ marginTop: 24 }}>Add relationship</h2>
              <div className="form">
                <input className="field" placeholder="from skill id" value={relTarget.id || ""} onChange={e => setRelTarget({ ...relTarget, id: Number(e.target.value) })} />
                <input className="field" placeholder="to canonical_name" value={relTarget.to} onChange={e => setRelTarget({ ...relTarget, to: e.target.value })} />
                <select className="field" value={relTarget.type} onChange={e => setRelTarget({ ...relTarget, type: e.target.value })}>
                  <option value="prerequisite">prerequisite</option><option value="related">related</option>
                  <option value="advanced_version">advanced_version</option><option value="alternative">alternative</option>
                  <option value="complementary">complementary</option>
                </select>
                <button className="btn secondary" onClick={addRelationship}>Add relationship</button>
              </div>
              <button className="linkbtn" style={{ marginTop: 16 }} onClick={reseed}>Re-run catalog seed (idempotent)</button>
            </div>
            <div className="card">
              <h2>Catalog ({skills.length})</h2>
              <div className="qlist" style={{ maxHeight: 600, overflowY: "auto" }}>
                {skills.map(s => (
                  <div key={s.id} className="qitem">
                    <div><b>{s.display_name}</b> <span className="muted">#{s.id} · {s.canonical_name} · {s.category}/{s.subcategory} · {s.difficulty}</span></div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === "resources" && (
          <div className="grid2" style={{ marginTop: 18 }}>
            <div className="card">
              <h2>Add a resource</h2>
              <div className="form">
                <input className="field" placeholder="skill canonical_name" value={newResource.skill_canonical_name} onChange={e => setNewResource({ ...newResource, skill_canonical_name: e.target.value })} />
                <input className="field" placeholder="title" value={newResource.title} onChange={e => setNewResource({ ...newResource, title: e.target.value })} />
                <input className="field" placeholder="provider" value={newResource.provider} onChange={e => setNewResource({ ...newResource, provider: e.target.value })} />
                <input className="field" placeholder="url (verified, real link only)" value={newResource.url} onChange={e => setNewResource({ ...newResource, url: e.target.value })} />
                <select className="field" value={newResource.resource_type} onChange={e => setNewResource({ ...newResource, resource_type: e.target.value })}>
                  {["course", "book", "documentation", "article", "video", "tutorial", "practice_platform", "project", "certification"].map(t => <option key={t}>{t}</option>)}
                </select>
                <select className="field" value={newResource.status} onChange={e => setNewResource({ ...newResource, status: e.target.value })}>
                  <option value="draft">draft</option><option value="published">published</option><option value="archived">archived</option>
                </select>
                <label className="checkbox-label"><input type="checkbox" checked={newResource.is_verified} onChange={e => setNewResource({ ...newResource, is_verified: e.target.checked })} /> Verified (required for candidates to see it)</label>
                <button className="btn" onClick={createResource}>Create resource</button>
              </div>
            </div>
            <div className="card">
              <h2>Resources ({resources.length})</h2>
              <div className="qlist" style={{ maxHeight: 600, overflowY: "auto" }}>
                {resources.map(r => (
                  <div key={r.id} className="qitem">
                    <div><b>{r.title}</b> <span className="muted">skill #{r.skill_id} · {r.resource_type} · {r.status}{r.is_verified ? " · verified" : " · unverified"}</span></div>
                    <button className="linkbtn" onClick={() => toggleResourceVerified(r)}>{r.is_verified ? "Unverify" : "Verify & publish"}</button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === "assessments" && (
          <div className="grid2" style={{ marginTop: 18 }}>
            <div className="card">
              <h2>Create an assessment</h2>
              <div className="form">
                <input className="field" placeholder="skill canonical_name" value={newAssessment.skill_canonical_name} onChange={e => setNewAssessment({ ...newAssessment, skill_canonical_name: e.target.value })} />
                <input className="field" placeholder="title" value={newAssessment.title} onChange={e => setNewAssessment({ ...newAssessment, title: e.target.value })} />
                <select className="field" value={newAssessment.status} onChange={e => setNewAssessment({ ...newAssessment, status: e.target.value })}>
                  <option value="draft">draft</option><option value="published">published</option>
                </select>
                <button className="btn" onClick={createAssessment}>Create assessment</button>
              </div>
              {assessments.map(a => <p key={a.id} className="muted">Created this session: #{a.id} — {a.title}</p>)}
            </div>
            <div className="card">
              <h2>Add a question</h2>
              <div className="form">
                <input className="field" placeholder="assessment id" value={newQuestion.assessment_id} onChange={e => setNewQuestion({ ...newQuestion, assessment_id: e.target.value })} />
                <input className="field" placeholder="prompt" value={newQuestion.prompt} onChange={e => setNewQuestion({ ...newQuestion, prompt: e.target.value })} />
                <input className="field" placeholder="options, comma-separated" value={newQuestion.options} onChange={e => setNewQuestion({ ...newQuestion, options: e.target.value })} />
                <input className="field" placeholder="correct_option index (0-based)" value={newQuestion.correct_option} onChange={e => setNewQuestion({ ...newQuestion, correct_option: e.target.value })} />
                <input className="field" placeholder="topic tag" value={newQuestion.topic} onChange={e => setNewQuestion({ ...newQuestion, topic: e.target.value })} />
                <button className="btn" onClick={addQuestion}>Add question</button>
              </div>
              <p className="muted">Remember to set the assessment's status to "published" (in the Skill Catalog admin flow above) before candidates can take it.</p>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
