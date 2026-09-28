"use client";
import { safeHref } from "@/lib/safe";
// V20.5 — AI Learning & Skill Intelligence frontend. Additive new route
// under /learning (linked from Nav.tsx, doesn't change any existing
// page). Same api() helper and card/field/btn/chip styling every other
// candidate page (frontend/src/app/resume/intelligence/page.tsx,
// /interview, etc.) already uses — one tabbed page per the pattern
// resume/intelligence established for a multi-section feature, rather
// than nine separate routes, to keep navigation and shared state (the
// target job id) in one place. Covers: Skill Profile, Skill Gap,
// Learning Dashboard, Learning Path, Resource Library, Assessment,
// Practice, Progress, Career Readiness, plus (Phase 4) Career Roadmap,
// learning streak, government exam resources, and structured project
// briefs woven into the Gap/Path/Practice/Progress tabs.
import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";

type Tab = "profile" | "gap" | "dashboard" | "path" | "resources" | "assessment" | "practice" | "progress" | "readiness" | "roadmap";
const TABS: { key: Tab; label: string }[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "profile", label: "Skill Profile" },
  { key: "gap", label: "Skill Gap" },
  { key: "path", label: "Learning Path" },
  { key: "roadmap", label: "Career Roadmap" },
  { key: "progress", label: "Progress" },
  { key: "resources", label: "Resource Library" },
  { key: "assessment", label: "Assessment" },
  { key: "practice", label: "Practice" },
  { key: "readiness", label: "Career Readiness" },
];

function ScoreBar({ label, score }: { label: string; score: number | null }) {
  const s = score ?? 0;
  const color = s >= 70 ? "var(--good)" : s >= 40 ? "var(--seal)" : "var(--bad)";
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
        <span className="muted">{label}</span>
        <span><b>{score === null ? "—" : score}</b>{score !== null ? "/100" : " (no data yet)"}</span>
      </div>
      <div style={{ background: "var(--line)", borderRadius: 6, height: 8, overflow: "hidden" }}>
        <div style={{ width: `${s}%`, background: color, height: "100%" }} />
      </div>
    </div>
  );
}

function SkillChip({ name }: { name: string }) {
  return <span className="pill" style={{ marginRight: 6, marginBottom: 6, display: "inline-block" }}>{name}</span>;
}

export default function LearningCenterPage() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState("");

  // Skill Profile
  const [skillQuery, setSkillQuery] = useState("");
  const [skillResults, setSkillResults] = useState<any[]>([]);
  const [graphSkill, setGraphSkill] = useState<any>(null);

  // Skill Gap
  const [gap, setGap] = useState<any>(null);

  // Dashboard
  const [plans, setPlans] = useState<any[]>([]);
  const [readinessQuick, setReadinessQuick] = useState<any>(null);
  const [practiceQuick, setPracticeQuick] = useState<any[]>([]);

  // Learning Path
  const [pathPreview, setPathPreview] = useState<any>(null);
  const [planTitle, setPlanTitle] = useState("My learning plan");

  // Resource Library
  const [resourceSkill, setResourceSkill] = useState("");
  const [resources, setResources] = useState<any[]>([]);

  // Assessment
  const [assessSkill, setAssessSkill] = useState("");
  const [assessments, setAssessments] = useState<any[]>([]);
  const [activeAssessment, setActiveAssessment] = useState<any>(null);
  const [questions, setQuestions] = useState<any[]>([]);
  const [attempt, setAttempt] = useState<any>(null);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [result, setResult] = useState<any>(null);

  // Practice
  const [practice, setPractice] = useState<any[]>([]);

  // Progress
  const [selectedPlan, setSelectedPlan] = useState<any>(null);
  const [progress, setProgress] = useState<any>(null);

  // Career Readiness
  const [readiness, setReadiness] = useState<any>(null);

  // Career Roadmap
  const [roadmap, setRoadmap] = useState<any>(null);

  function jobQuery() { return jobId ? `?target_job_id=${jobId}` : ""; }

  async function loadDashboard() {
    setErr(""); setBusy(true);
    try {
      const [p, r, pr] = await Promise.all([
        api("/learning-plans"),
        api(`/career-readiness${jobQuery()}`),
        api(`/practice-recommendations${jobQuery()}`),
      ]);
      setPlans(p); setReadinessQuick(r); setPracticeQuick(pr.slice(0, 5));
    } catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  useEffect(() => { loadDashboard(); }, []);

  async function searchSkills() {
    setBusy(true); setErr("");
    try { setSkillResults(await api(`/skills${skillQuery ? `?q=${encodeURIComponent(skillQuery)}` : ""}`)); }
    catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }
  useEffect(() => { searchSkills(); }, []);

  async function viewGraph(name: string) {
    setBusy(true); setErr("");
    try { setGraphSkill(await api(`/skills/${encodeURIComponent(name)}/graph`)); }
    catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function loadGap() {
    setBusy(true); setErr(""); setGap(null);
    try { setGap(await api(`/skill-intelligence/gap${jobQuery()}`)); }
    catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function loadPathPreview() {
    setBusy(true); setErr(""); setPathPreview(null);
    try { setPathPreview(await api(`/learning-path/preview${jobQuery()}`)); }
    catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function createPlan() {
    setBusy(true); setErr("");
    try {
      const body: any = { title: planTitle };
      if (jobId) body.target_job_id = Number(jobId);
      const plan = await api("/learning-plans", { method: "POST", body: JSON.stringify(body) });
      await loadDashboard();
      setSelectedPlan(plan);
      setTab("progress");
    } catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function loadResources() {
    if (!resourceSkill.trim()) return;
    setBusy(true); setErr(""); setResources([]);
    try { setResources(await api(`/resources?skill=${encodeURIComponent(resourceSkill)}`)); }
    catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function loadAssessments() {
    setBusy(true); setErr(""); setAssessments([]);
    try { setAssessments(await api(`/assessments${assessSkill ? `?skill=${encodeURIComponent(assessSkill)}` : ""}`)); }
    catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function startAssessment(a: any) {
    setBusy(true); setErr(""); setResult(null); setAnswers({});
    try {
      const qs = await api(`/assessments/${a.id}/questions`);
      const att = await api(`/assessments/${a.id}/attempts`, { method: "POST" });
      setActiveAssessment(a); setQuestions(qs); setAttempt(att);
    } catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function submitAssessment() {
    if (!attempt) return;
    setBusy(true); setErr("");
    try {
      const body = { answers: Object.entries(answers).map(([qid, opt]) => ({ question_id: Number(qid), selected_option: opt })) };
      const r = await api(`/attempts/${attempt.id}/submit`, { method: "POST", body: JSON.stringify(body) });
      setResult(r);
    } catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function loadPractice() {
    setBusy(true); setErr("");
    try { setPractice(await api(`/practice-recommendations${jobQuery()}`)); }
    catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function openPlanProgress(p: any) {
    setSelectedPlan(p); setBusy(true); setErr("");
    try { setProgress(await api(`/learning-plans/${p.id}/progress`)); }
    catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function moduleAction(planId: number, moduleId: number, action: "start" | "complete" | "skip") {
    setBusy(true); setErr("");
    try {
      await api(`/learning-plans/${planId}/modules/${moduleId}/${action}`, { method: "POST" });
      const p = await api(`/learning-plans/${planId}`);
      setSelectedPlan(p);
      setProgress(await api(`/learning-plans/${planId}/progress`));
      loadDashboard();
    } catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function setPlanStatus(planId: number, status: string) {
    setBusy(true); setErr("");
    try {
      const p = await api(`/learning-plans/${planId}/status`, { method: "PUT", body: JSON.stringify({ status }) });
      setSelectedPlan(p); loadDashboard();
    } catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function loadReadiness() {
    setBusy(true); setErr(""); setReadiness(null);
    try { setReadiness(await api(`/career-readiness${jobQuery()}`)); }
    catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  async function loadRoadmap() {
    setBusy(true); setErr(""); setRoadmap(null);
    try { setRoadmap(await api(`/career-roadmap${jobQuery()}`)); }
    catch (e: any) { setErr(formatApiError(e, e.message)); } finally { setBusy(false); }
  }

  return (
    <main id="main" className="page">
      <div className="container">
        <div className="pagehead">
          <div>
            <span className="eyebrow">V20.5</span>
            <h1>Learning &amp; Skill Intelligence</h1>
            <p className="muted">Your skill gap, personalized learning path, practice recommendations, and career readiness — all in one place.</p>
          </div>
          <div className="field-label" style={{ minWidth: 220 }}>
            Target job ID (optional)
            <input className="field" placeholder="e.g. 42" value={jobId} onChange={e => setJobId(e.target.value.replace(/\D/g, ""))} />
          </div>
        </div>

        <div className="filters">
          {TABS.map(t => (
            <button key={t.key} className={`chip ${tab === t.key ? "chip-active" : ""}`} onClick={() => setTab(t.key)}>{t.label}</button>
          ))}
        </div>

        {err && <p className="error">{err}</p>}
        {busy && <p className="loading">Loading…</p>}

        {tab === "dashboard" && (
          <div className="grid2" style={{ marginTop: 18 }}>
            <div className="card">
              <h2>Career readiness</h2>
              {readinessQuick ? (
                <>
                  <ScoreBar label="Role readiness" score={readinessQuick.role_readiness} />
                  {readinessQuick.components.map((c: any) => (
                    <ScoreBar key={c.name} label={c.name.replace(/_/g, " ")} score={c.score} />
                  ))}
                </>
              ) : <p className="muted">No data yet.</p>}
              <button className="linkbtn" onClick={() => setTab("readiness")}>View full breakdown →</button>
            </div>
            <div className="card">
              <h2>Active learning plans</h2>
              {plans.length === 0 && <p className="empty">No learning plans yet. Build one from your Learning Path tab.</p>}
              {plans.map(p => (
                <div key={p.id} className="qitem" style={{ marginBottom: 8 }}>
                  <div><b>{p.title}</b><br /><span className="muted">{p.status} · {p.modules.filter((m: any) => m.status === "completed").length}/{p.modules.length} modules done{p.current_streak_days > 0 ? ` · 🔥 ${p.current_streak_days}-day streak` : ""}</span></div>
                  <button className="linkbtn" onClick={() => { openPlanProgress(p); setTab("progress"); }}>Open →</button>
                </div>
              ))}
            </div>
            <div className="card" style={{ gridColumn: "1 / -1" }}>
              <h2>Top practice recommendations</h2>
              {practiceQuick.length === 0 && <p className="empty">No recommendations yet — take an assessment or set a target job.</p>}
              {practiceQuick.map((s: any, i: number) => (
                <div key={i} className="qitem" style={{ marginBottom: 8 }}>
                  <div><b>{s.skill.display_name}</b> — <span className="muted">{s.recommendation_type.replace(/_/g, " ")}</span><br /><span className="muted">{s.reason}</span></div>
                </div>
              ))}
              <button className="linkbtn" onClick={() => setTab("practice")}>View all →</button>
            </div>
          </div>
        )}

        {tab === "profile" && (
          <div className="card">
            <h2>Skill Profile — browse the catalog</h2>
            <div className="search">
              <input className="field" placeholder="Search skills (e.g. python, react)" value={skillQuery} onChange={e => setSkillQuery(e.target.value)} />
              <button className="btn" onClick={searchSkills}>Search</button>
            </div>
            <div style={{ marginTop: 16 }}>
              {skillResults.map(s => (
                <span key={s.id} onClick={() => viewGraph(s.canonical_name)} style={{ cursor: "pointer" }}>
                  <SkillChip name={`${s.display_name} · ${s.subcategory}`} />
                </span>
              ))}
            </div>
            {graphSkill && (
              <div className="section">
                <h2>{graphSkill.skill.display_name} — skill graph</h2>
                <p className="muted">Learning order: {graphSkill.learning_order.map((s: any) => s.display_name).join(" → ")}</p>
                <div className="grid2">
                  <div><b>Prerequisites</b><div>{graphSkill.prerequisites.map((s: any) => <SkillChip key={s.id} name={s.display_name} />)}{graphSkill.prerequisites.length === 0 && <span className="muted">None</span>}</div></div>
                  <div><b>Related</b><div>{graphSkill.related.map((s: any) => <SkillChip key={s.id} name={s.display_name} />)}{graphSkill.related.length === 0 && <span className="muted">None</span>}</div></div>
                  <div><b>Advanced versions</b><div>{graphSkill.advanced_versions.map((s: any) => <SkillChip key={s.id} name={s.display_name} />)}{graphSkill.advanced_versions.length === 0 && <span className="muted">None</span>}</div></div>
                  <div><b>Alternatives</b><div>{graphSkill.alternatives.map((s: any) => <SkillChip key={s.id} name={s.display_name} />)}{graphSkill.alternatives.length === 0 && <span className="muted">None</span>}</div></div>
                </div>
              </div>
            )}
          </div>
        )}

        {tab === "gap" && (
          <div className="card">
            <h2>Skill Gap</h2>
            <button className="btn" onClick={loadGap}>Compute my skill gap{jobId ? ` vs. job #${jobId}` : ""}</button>
            {gap && (
              <div className="section">
                <p className="muted">Signals used: {gap.signals_used.join(", ") || "none"}</p>
                {gap.signals_unavailable.length > 0 && <p className="muted">Not available yet: {gap.signals_unavailable.join("; ")}</p>}
                {gap.is_government_target && (
                  <div className="card" style={{ background: "var(--paper)", marginBottom: 16 }}>
                    <h2>Government exam — verified resources</h2>
                    {gap.verified_exam_resources.length === 0 && <p className="muted">No verified syllabus/exam-prep resources linked to this listing yet.</p>}
                    {gap.verified_exam_resources.map((r: any, i: number) => (
                      <div key={i} className="qitem">
                        <div><b>{r.title}</b> <span className="pill">{r.resource_type}</span><br /><span className="muted">{r.organization} · {r.exam_name}</span></div>
                        <a href={safeHref(r.url)} target="_blank" rel="noreferrer" className="linkbtn">Open →</a>
                      </div>
                    ))}
                    <p className="muted" style={{ marginTop: 8 }}>Eligibility and syllabus details are shown only from official/verified sources — never generated.</p>
                  </div>
                )}
                <h2>Matched skills</h2>
                <div>{gap.matched_skills.map((s: string) => <SkillChip key={s} name={s} />)}{gap.matched_skills.length === 0 && <span className="muted">None yet</span>}</div>
                <h2>Priority gaps</h2>
                {gap.priority_skills.map((it: any) => (
                  <div key={it.canonical_name} className="qitem" style={{ marginBottom: 8 }}>
                    <div><b>{it.display_name}</b> <span className="pill">{it.priority_score}</span><br /><span className="muted">{it.reason}</span></div>
                  </div>
                ))}
                {gap.priority_skills.length === 0 && <p className="empty">No priority gaps right now.</p>}
                <h2>Recommended</h2>
                <div>{gap.recommended_skills.map((it: any) => <SkillChip key={it.canonical_name} name={it.display_name} />)}</div>
                {gap.unrecognized_inputs.length > 0 && <p className="muted" style={{ marginTop: 10 }}>Not in the catalog yet: {gap.unrecognized_inputs.join(", ")}</p>}
              </div>
            )}
          </div>
        )}

        {tab === "path" && (
          <div className="card">
            <h2>Learning Path</h2>
            <button className="btn" onClick={loadPathPreview}>Preview my learning path</button>
            {pathPreview && (
              <div className="section">
                {pathPreview.signals_unavailable.length > 0 && <p className="muted">Based on limited data: {pathPreview.signals_unavailable.join("; ")}</p>}
                <div className="qlist">
                  {pathPreview.steps.map((s: any, i: number) => (
                    <div key={i} className="qitem">
                      <div>
                        <b>{i + 1}. {s.skill.display_name}</b> <span className="muted">({s.skill.difficulty})</span><br />
                        <span className="muted">{s.reason}</span><br />
                        {s.resource ? <a href={safeHref(s.resource.url)} target="_blank" rel="noreferrer" className="linkbtn" style={{ padding: 0 }}>{s.resource.title} ({s.resource.provider})</a> : <span className="muted">No verified resource yet</span>}
                      </div>
                    </div>
                  ))}
                </div>
                {pathPreview.unresourced_skill_names.length > 0 && <p className="muted">No verified resource yet for: {pathPreview.unresourced_skill_names.join(", ")}</p>}
                <div className="form" style={{ marginTop: 16 }}>
                  <label className="field-label">Plan title
                    <input className="field" value={planTitle} onChange={e => setPlanTitle(e.target.value)} />
                  </label>
                  <button className="btn" onClick={createPlan}>Create a learning plan from this path</button>
                </div>
              </div>
            )}
          </div>
        )}

        {tab === "resources" && (
          <div className="card">
            <h2>Resource Library</h2>
            <div className="search">
              <input className="field" placeholder="Skill name (e.g. docker)" value={resourceSkill} onChange={e => setResourceSkill(e.target.value)} />
              <button className="btn" onClick={loadResources}>Search</button>
            </div>
            <div className="qlist" style={{ marginTop: 16 }}>
              {resources.map(r => (
                <div key={r.id} className="qitem">
                  <div>
                    <b>{r.title}</b> <span className="pill">{r.resource_type}</span><br />
                    <span className="muted">{r.provider} · {r.difficulty} · {r.is_free ? "Free" : "Paid"}{r.rating ? ` · ${r.rating}★` : ""}</span>
                  </div>
                  {r.url && <a href={safeHref(r.url)} target="_blank" rel="noreferrer" className="linkbtn">Open →</a>}
                </div>
              ))}
              {resources.length === 0 && <p className="empty">Search a skill to see verified resources.</p>}
            </div>
          </div>
        )}

        {tab === "assessment" && (
          <div className="card">
            <h2>Assessment</h2>
            {!activeAssessment && (
              <>
                <div className="search">
                  <input className="field" placeholder="Skill name (e.g. python)" value={assessSkill} onChange={e => setAssessSkill(e.target.value)} />
                  <button className="btn" onClick={loadAssessments}>Find assessments</button>
                </div>
                <div className="qlist" style={{ marginTop: 16 }}>
                  {assessments.map(a => (
                    <div key={a.id} className="qitem">
                      <div><b>{a.title}</b> <span className="muted">({a.assessment_type}, {a.difficulty})</span></div>
                      <button className="linkbtn" onClick={() => startAssessment(a)}>Start →</button>
                    </div>
                  ))}
                  {assessments.length === 0 && <p className="empty">Search a skill to find assessments.</p>}
                </div>
              </>
            )}
            {activeAssessment && !result && (
              <div className="form">
                <h2>{activeAssessment.title}</h2>
                {questions.map(q => (
                  <div key={q.id} className="card">
                    <p><b>{q.prompt}</b></p>
                    {q.options.map((opt: string, idx: number) => (
                      <label key={idx} className="checkbox-label" style={{ display: "block" }}>
                        <input type="radio" name={`q${q.id}`} checked={answers[q.id] === idx} onChange={() => setAnswers({ ...answers, [q.id]: idx })} /> {opt}
                      </label>
                    ))}
                  </div>
                ))}
                <div className="actions">
                  <button className="btn" onClick={submitAssessment}>Submit</button>
                  <button className="secondary btn" onClick={() => { setActiveAssessment(null); setQuestions([]); setAttempt(null); }}>Cancel</button>
                </div>
              </div>
            )}
            {result && (
              <div className="section">
                <h2>Result: {result.score_percentage}% ({result.correct_count}/{result.total_questions})</h2>
                {result.weak_topics.length > 0 && <p className="muted">Weak topics: {result.weak_topics.join(", ")}</p>}
                <button className="linkbtn" onClick={() => { setActiveAssessment(null); setQuestions([]); setAttempt(null); setResult(null); }}>Take another →</button>
              </div>
            )}
          </div>
        )}

        {tab === "practice" && (
          <div className="card">
            <h2>Practice Recommendations</h2>
            <button className="btn" onClick={loadPractice}>Refresh</button>
            <div className="qlist" style={{ marginTop: 16 }}>
              {practice.map((s: any, i: number) => (
                <div key={i} className="qitem">
                  <div>
                    <b>{s.skill.display_name}</b> <span className="pill">{s.recommendation_type.replace(/_/g, " ")}</span> <span className="muted">priority {s.priority_score}</span><br />
                    <span className="muted">{s.reason}</span>
                    {s.project && (
                      <div className="card" style={{ marginTop: 8, background: "var(--paper)" }}>
                        <b>{s.project.title}</b>
                        {s.project.objective && <p className="muted"><b>Objective:</b> {s.project.objective}</p>}
                        {s.project.requirements && <p className="muted"><b>Requirements:</b> {s.project.requirements}</p>}
                        {s.project.expected_output && <p className="muted"><b>Expected output:</b> {s.project.expected_output}</p>}
                        {s.project.evaluation_criteria && <p className="muted"><b>Evaluation criteria:</b> {s.project.evaluation_criteria}</p>}
                        {s.project.url && <a href={safeHref(s.project.url)} target="_blank" rel="noreferrer" className="linkbtn" style={{ padding: 0 }}>Reference →</a>}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {practice.length === 0 && <p className="empty">No recommendations yet.</p>}
            </div>
          </div>
        )}

        {tab === "progress" && (
          <div className="detailgrid">
            <div className="card">
              <h2>{selectedPlan ? selectedPlan.title : "Select a plan"}</h2>
              {!selectedPlan && (
                <div className="qlist">
                  {plans.map(p => (
                    <div key={p.id} className="qitem">
                      <b>{p.title}</b>
                      <button className="linkbtn" onClick={() => openPlanProgress(p)}>Open →</button>
                    </div>
                  ))}
                  {plans.length === 0 && <p className="empty">No plans yet — create one from Learning Path.</p>}
                </div>
              )}
              {selectedPlan && (
                <>
                  <p className="muted">Status: {selectedPlan.status}</p>
                  <div className="actions" style={{ marginBottom: 16 }}>
                    {selectedPlan.status === "active" && <button className="secondary btn" onClick={() => setPlanStatus(selectedPlan.id, "paused")}>Pause</button>}
                    {selectedPlan.status === "paused" && <button className="btn" onClick={() => setPlanStatus(selectedPlan.id, "active")}>Resume</button>}
                    {selectedPlan.status !== "completed" && selectedPlan.status !== "cancelled" && <button className="secondary btn" onClick={() => setPlanStatus(selectedPlan.id, "completed")}>Mark complete</button>}
                  </div>
                  <div className="qlist">
                    {selectedPlan.modules.map((m: any) => (
                      <div key={m.id} className="qitem">
                        <div><b>Module #{m.order_index + 1}</b> <span className="muted">skill_id {m.skill_id} · {m.status} · {m.time_spent_minutes}m logged</span></div>
                        <div className="actions">
                          {m.status === "not_started" && <button className="linkbtn" onClick={() => moduleAction(selectedPlan.id, m.id, "start")}>Start</button>}
                          {m.status !== "completed" && m.status !== "skipped" && <button className="linkbtn" onClick={() => moduleAction(selectedPlan.id, m.id, "complete")}>Complete</button>}
                          {m.status !== "completed" && m.status !== "skipped" && <button className="linkbtn" onClick={() => moduleAction(selectedPlan.id, m.id, "skip")}>Skip</button>}
                        </div>
                      </div>
                    ))}
                  </div>
                  <button className="linkbtn" onClick={() => setSelectedPlan(null)}>← Back to plan list</button>
                </>
              )}
            </div>
            <div className="stickycard card">
              <h2>Progress</h2>
              {progress ? (
                <>
                  <ScoreBar label="Completion" score={progress.completion_percentage} />
                  <p className="muted">{progress.completed} completed · {progress.in_progress} in progress · {progress.skipped} skipped · {progress.not_started} not started</p>
                  <p className="muted">{progress.total_time_spent_minutes} minutes logged total</p>
                  <div className="card" style={{ marginTop: 12, background: "var(--paper)" }}>
                    <b>🔥 {progress.current_streak_days}-day streak</b>
                    <p className="muted">Longest streak: {progress.longest_streak_days} day{progress.longest_streak_days === 1 ? "" : "s"}</p>
                  </div>
                </>
              ) : <p className="muted">Open a plan to see progress.</p>}
            </div>
          </div>
        )}

        {tab === "readiness" && (
          <div className="card">
            <h2>Career Readiness</h2>
            <button className="btn" onClick={loadReadiness}>Compute my readiness{jobId ? ` vs. job #${jobId}` : ""}</button>
            {readiness && (
              <div className="section">
                <ScoreBar label="Role readiness" score={readiness.role_readiness} />
                <p className="muted">{readiness.explanation}</p>
                <div className="grid2" style={{ marginTop: 16 }}>
                  {readiness.components.map((c: any) => (
                    <div key={c.name} className="card">
                      <h2 style={{ textTransform: "capitalize" }}>{c.name.replace(/_/g, " ")}</h2>
                      <ScoreBar label="Score" score={c.score} />
                      <p className="muted">{c.reason}</p>
                      {c.weak_areas.length > 0 && <p className="muted"><b>Weak areas:</b> {c.weak_areas.join(", ")}</p>}
                      <p className="muted"><b>Recommended action:</b> {c.recommended_action}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {tab === "roadmap" && (
          <div className="card">
            <h2>Career Roadmap</h2>
            <button className="btn" onClick={loadRoadmap}>Build my roadmap{jobId ? ` toward job #${jobId}` : ""}</button>
            {roadmap && (
              <div className="section">
                <p className="muted">Target: <b>{roadmap.goal}</b></p>
                <div style={{ display: "flex", flexDirection: "column", gap: 0, marginTop: 16 }}>
                  {roadmap.stages.map((s: any, i: number) => (
                    <div key={s.stage} style={{ display: "flex", gap: 12 }}>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                        <div style={{ width: 28, height: 28, borderRadius: "50%", background: s.items.length > 0 || i === 0 || i === roadmap.stages.length - 1 ? "var(--good)" : "var(--line)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, flexShrink: 0 }}>{i + 1}</div>
                        {i < roadmap.stages.length - 1 && <div style={{ width: 2, flex: 1, background: "var(--line)", minHeight: 24 }} />}
                      </div>
                      <div style={{ paddingBottom: 20 }}>
                        <b>{s.stage}</b><br />
                        <span className="muted">{s.summary}</span>
                        {s.items.length > 0 && (
                          <div style={{ marginTop: 6 }}>
                            {s.items.slice(0, 8).map((it: string, j: number) => <SkillChip key={j} name={it} />)}
                            {s.items.length > 8 && <span className="muted"> +{s.items.length - 8} more</span>}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
