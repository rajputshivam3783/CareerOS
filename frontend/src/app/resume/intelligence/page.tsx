"use client";
// V20.2 — AI Resume Intelligence. Additive new route under the
// existing /resume page (linked from there, doesn't change it) — same
// api() helper and card/field/btn styling every other candidate page
// (frontend/src/app/resume/page.tsx, /applications, etc.) already uses.
import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";

type Tab = "score" | "ats" | "recommendations" | "job-match" | "bullet" | "summary" | "project";
const TABS: { key: Tab; label: string }[] = [
  { key: "score", label: "Resume score" },
  { key: "ats", label: "ATS analysis" },
  { key: "recommendations", label: "Recommendations" },
  { key: "job-match", label: "Job match & skill gap" },
  { key: "bullet", label: "Bullet improver" },
  { key: "summary", label: "Summary generator" },
  { key: "project", label: "Project analyzer" },
];

function ScoreBar({ label, score }: { label: string; score: number }) {
  const color = score >= 70 ? "var(--good)" : score >= 40 ? "var(--seal)" : "var(--bad)";
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
        <span className="muted">{label}</span><span><b>{score}</b>/100</span>
      </div>
      <div style={{ background: "var(--line)", borderRadius: 6, height: 8, overflow: "hidden" }}>
        <div style={{ width: `${score}%`, background: color, height: "100%" }} />
      </div>
    </div>
  );
}

export default function ResumeIntelligencePage() {
  const [tab, setTab] = useState<Tab>("score");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const [analysis, setAnalysis] = useState<any>(null);
  const [ats, setAts] = useState<any>(null);
  const [recs, setRecs] = useState<any>(null);
  const [jobId, setJobId] = useState("");
  const [jobMatch, setJobMatch] = useState<any>(null);
  const [skillGap, setSkillGap] = useState<any>(null);
  const [jobAdvice, setJobAdvice] = useState<any>(null);

  const [bulletText, setBulletText] = useState("");
  const [bulletResult, setBulletResult] = useState<any>(null);
  const [targetRole, setTargetRole] = useState("");
  const [summaryResult, setSummaryResult] = useState<any>(null);
  const [projectText, setProjectText] = useState("");
  const [projectResult, setProjectResult] = useState<any>(null);

  async function loadCore() {
    try {
      setErr("");
      const [a, atsBody, r] = await Promise.all([
        api("/resume-ai/analysis"),
        api("/resume-ai/ats"),
        api("/resume-ai/recommendations"),
      ]);
      setAnalysis(a); setAts(atsBody); setRecs(r.recommendations);
    } catch (e: any) { setErr(e.message); }
  }

  useEffect(() => { loadCore(); }, []);

  async function runJobMatch() {
    if (!jobId) return;
    setBusy(true); setErr("");
    try {
      const [match, advice] = await Promise.all([
        api(`/resume-ai/job-match/${jobId}`),
        api(`/resume-ai/job-advice/${jobId}`),
      ]);
      setJobMatch(match.match); setSkillGap(match.skill_gap); setJobAdvice(advice);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function runBulletImprove() {
    if (!bulletText.trim()) return;
    setBusy(true); setErr(""); setBulletResult(null);
    try { setBulletResult(await api("/resume-ai/bullet-improve", { method: "POST", body: JSON.stringify({ bullet: bulletText }) })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function runSummary() {
    if (!targetRole.trim()) return;
    setBusy(true); setErr(""); setSummaryResult(null);
    try { setSummaryResult(await api("/resume-ai/summary", { method: "POST", body: JSON.stringify({ target_role: targetRole }) })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function runProjectImprove() {
    if (!projectText.trim()) return;
    setBusy(true); setErr(""); setProjectResult(null);
    try { setProjectResult(await api("/resume-ai/project-improve", { method: "POST", body: JSON.stringify({ project_text: projectText }) })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  const overall = analysis?.scores?.overall;
  const components = analysis?.scores?.components;

  return (
    <main className="container page">
      <span className="eyebrow">AI resume intelligence</span>
      <h1>Resume intelligence</h1>
      <p className="muted">
        Every score below is computed directly from your uploaded resume — nothing here is guessed. Missing
        information is reported as "Not found in resume" rather than invented. Upload or update your resume on
        the <a href="/resume">Resume page</a> first.
      </p>
      {err && <p className="error">{err}</p>}

      <div className="filters">
        {TABS.map((t) => <button key={t.key} className={`chip ${tab === t.key ? "chip-active" : ""}`} onClick={() => setTab(t.key)}>{t.label}</button>)}
      </div>

      {tab === "score" && (
        <div className="card" style={{ marginTop: 18 }}>
          {!analysis && !err && <p className="muted">Loading...</p>}
          {overall && (
            <>
              <h2>Resume quality: {overall.score}/100</h2>
              <ul className="muted" style={{ fontSize: 13 }}>{overall.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
              <div style={{ marginTop: 16 }}>
                {components && Object.entries(components).map(([name, c]: any) => (
                  <ScoreBar key={name} label={name.replace(/_/g, " ")} score={c.score} />
                ))}
              </div>
              {components && (
                <details style={{ marginTop: 12 }}>
                  <summary className="muted">Why these scores? (click to expand)</summary>
                  {Object.entries(components).map(([name, c]: any) => (
                    <div key={name} style={{ marginTop: 8 }}>
                      <b style={{ textTransform: "capitalize" }}>{name.replace(/_/g, " ")}</b>
                      <ul className="muted" style={{ fontSize: 13 }}>{c.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
                    </div>
                  ))}
                </details>
              )}
            </>
          )}
        </div>
      )}

      {tab === "ats" && ats && (
        <div className="card" style={{ marginTop: 18 }}>
          <h2>ATS readability: <span className={`badge badge-${ats.readability === "good" ? "active" : ats.readability === "fair" ? "open" : "paused"}`}>{ats.readability}</span></h2>
          <p className="muted" style={{ marginTop: 8 }}>Present sections: {ats.structure.present.join(", ") || "none"}</p>
          <p className="muted">Missing sections: {ats.structure.missing.join(", ") || "none"}</p>
          <h3 style={{ marginTop: 12 }}>Formatting risks</h3>
          <ul className="muted" style={{ fontSize: 13 }}>{ats.formatting_risks.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
          <h3 style={{ marginTop: 12 }}>Keyword placement</h3>
          <p className="muted" style={{ fontSize: 13 }}>{ats.keyword_placement.note}</p>
          <h3 style={{ marginTop: 12 }}>Action verbs & achievements</h3>
          <p className="muted" style={{ fontSize: 13 }}>{ats.action_verbs.note}</p>
          <p className="muted" style={{ fontSize: 13 }}>{ats.achievement_statements.note}</p>
        </div>
      )}

      {tab === "recommendations" && (
        <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
          {(recs || []).map((r: any, i: number) => (
            <div className="card" key={i}>
              <span className="pill">{r.area}</span>
              <span className={`badge badge-${r.priority === "high" ? "paused" : r.priority === "medium" ? "open" : "active"}`} style={{ marginLeft: 8 }}>{r.priority} priority</span>
              <p style={{ marginTop: 8 }}><b>Why:</b> {r.reason}</p>
              <p className="muted" style={{ fontSize: 13 }}><b>Impact:</b> {r.impact}</p>
              <p style={{ marginTop: 8 }}><b>Do this:</b> {r.suggested_action}</p>
            </div>
          ))}
          {!recs?.length && <div className="empty">Loading recommendations...</div>}
        </div>
      )}

      {tab === "job-match" && (
        <>
          <div className="card form" style={{ marginTop: 18 }}>
            <label className="field-label">Job ID
              <input className="field" type="number" value={jobId} onChange={(e) => setJobId(e.target.value)} placeholder="e.g. 12" />
            </label>
            <div className="actions"><button className="btn" onClick={runJobMatch} disabled={busy}>Compare against this job</button></div>
          </div>

          {jobMatch && (
            <div className="card" style={{ marginTop: 18 }}>
              <h2>Overall match: {jobMatch.overall}%</h2>
              <ScoreBar label="Skills" score={jobMatch.skills.score} />
              <ScoreBar label="Experience" score={jobMatch.experience.score} />
              <ScoreBar label="Education" score={jobMatch.education.score} />
              <ScoreBar label="Keywords" score={jobMatch.keywords.score} />
              <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>{jobMatch.skills.explanation}</p>
              <p className="muted" style={{ fontSize: 13 }}>{jobMatch.experience.explanation}</p>
              <p className="muted" style={{ fontSize: 13 }}>{jobMatch.education.explanation}</p>
              <p className="muted" style={{ fontSize: 13 }}>{jobMatch.keywords.explanation}</p>
              <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>{jobMatch.location_note}</p>
              <p className="muted" style={{ fontSize: 13 }}>{jobMatch.job_type_note}</p>
            </div>
          )}

          {skillGap && (
            <div className="card" style={{ marginTop: 18 }}>
              <h2>Skill gap</h2>
              <p><b>Matched:</b> {skillGap.matched_skills.join(", ") || "none"}</p>
              <p><b>Missing:</b> {skillGap.missing_skills.join(", ") || "none"}</p>
              <p><b>Weak (claimed but not reinforced elsewhere):</b> {skillGap.weak_skills.join(", ") || "none"}</p>
              <p><b>Recommended to learn:</b> {skillGap.recommended_skills.join(", ") || "none"}</p>
              {Object.keys(skillGap.transferable_skills || {}).length > 0 && (
                <p><b>Transferable:</b> {Object.entries(skillGap.transferable_skills).map(([gap, from]: any) => `${gap} (via ${from.join(", ")})`).join("; ")}</p>
              )}
              <h3 style={{ marginTop: 12 }}>Prioritized gaps</h3>
              <ul className="muted" style={{ fontSize: 13 }}>
                {skillGap.prioritized_gaps.map((g: any, i: number) => <li key={i}><b>{g.skill}</b> — {g.reason}</li>)}
              </ul>
            </div>
          )}

          {jobAdvice && (
            <div className="card" style={{ marginTop: 18 }}>
              <h2>Job-specific advice</h2>
              {jobAdvice.narrative && <p>{jobAdvice.narrative}</p>}
              {!jobAdvice.narrative && <p className="muted">No AI provider is configured — showing the structured breakdown directly.</p>}
              <p style={{ marginTop: 8 }}><b>Skills to highlight:</b> {jobAdvice.skills_to_highlight.join(", ") || "none"}</p>
              <p><b>Missing keywords:</b> {jobAdvice.missing_keywords.join(", ") || "none"}</p>
              <p><b>Sections to improve:</b> {jobAdvice.sections_to_improve.join("; ")}</p>
            </div>
          )}
        </>
      )}

      {tab === "bullet" && (
        <div className="card form" style={{ marginTop: 18 }}>
          <h2>Bullet improver</h2>
          <p className="muted">Paste one resume bullet. Rewrites only reword what's already there — no invented companies, metrics, or technologies.</p>
          <textarea className="field" rows={3} value={bulletText} onChange={(e) => setBulletText(e.target.value)} placeholder="e.g. Responsible for building internal tools using Python" />
          <div className="actions"><button className="btn" onClick={runBulletImprove} disabled={busy}>Improve this bullet</button></div>
          {bulletResult && (
            <div style={{ marginTop: 12 }}>
              <p className="muted" style={{ fontSize: 12 }}>Source: {bulletResult.source === "ai" ? `AI (${bulletResult.provider})` : bulletResult.source}</p>
              {bulletResult.variants.map((v: string, i: number) => <p key={i} className="card" style={{ marginTop: 8, padding: 12 }}>{v}</p>)}
            </div>
          )}
        </div>
      )}

      {tab === "summary" && (
        <div className="card form" style={{ marginTop: 18 }}>
          <h2>Summary generator</h2>
          <p className="muted">Generated only from what's already on your resume — never a claimed title, employer, or metric you haven't stated.</p>
          <label className="field-label">Target role
            <input className="field" value={targetRole} onChange={(e) => setTargetRole(e.target.value)} placeholder="e.g. Backend Developer" />
          </label>
          <div className="actions"><button className="btn" onClick={runSummary} disabled={busy}>Generate summary</button></div>
          {summaryResult && (
            <div style={{ marginTop: 12 }}>
              <p className="muted" style={{ fontSize: 12 }}>Source: {summaryResult.source === "ai" ? `AI (${summaryResult.provider})` : summaryResult.source}</p>
              <p className="card" style={{ padding: 12 }}>{summaryResult.summary}</p>
            </div>
          )}
        </div>
      )}

      {tab === "project" && (
        <div className="card form" style={{ marginTop: 18 }}>
          <h2>Project analyzer</h2>
          <p className="muted">Paste a project description. Suggestions only reference technologies you already mentioned.</p>
          <textarea className="field" rows={4} value={projectText} onChange={(e) => setProjectText(e.target.value)} placeholder="Describe one of your projects..." />
          <div className="actions"><button className="btn" onClick={runProjectImprove} disabled={busy}>Analyze project</button></div>
          {projectResult && (
            <div style={{ marginTop: 12 }}>
              <p className="muted" style={{ fontSize: 12 }}>Source: {projectResult.source === "ai" ? `AI (${projectResult.provider})` : projectResult.source}</p>
              <ul>{projectResult.suggestions.map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
