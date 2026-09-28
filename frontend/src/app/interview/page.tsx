"use client";
// V20.4 — AI Interview & Mock Interview System. Additive new route;
// reuses api()/card/field/btn/chip styling every other candidate page
// already uses (see frontend/src/app/career-copilot/page.tsx).
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, formatApiError } from "@/lib/api";

const INTERVIEW_TYPES = [
  { value: "technical", label: "Technical" }, { value: "hr", label: "HR" },
  { value: "behavioral", label: "Behavioral" }, { value: "resume_based", label: "Resume-Based" },
  { value: "job_specific", label: "Job-Specific" }, { value: "coding", label: "Coding" },
  { value: "data_science", label: "Data Science" }, { value: "system_design", label: "System Design" },
  { value: "mixed", label: "Mixed" }, { value: "custom", label: "Custom" },
];
const DIFFICULTIES = ["easy", "medium", "hard", "adaptive"];
const EXPERIENCE_LEVELS = ["entry", "mid", "senior", "lead"];

type Tab = "setup" | "history";

export default function InterviewLandingPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("setup");
  const [err, setErr] = useState("");

  // Setup form state
  const [interviewType, setInterviewType] = useState("technical");
  const [jobId, setJobId] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [experienceLevel, setExperienceLevel] = useState("mid");
  const [difficulty, setDifficulty] = useState("medium");
  const [durationMinutes, setDurationMinutes] = useState(30);
  const [questionCount, setQuestionCount] = useState(8);
  const [focusSkills, setFocusSkills] = useState("");
  const [programmingLanguage, setProgrammingLanguage] = useState("python");
  const [creating, setCreating] = useState(false);

  // History state
  const [history, setHistory] = useState<any>(null);
  const [sessions, setSessions] = useState<any[]>([]);

  useEffect(() => {
    if (tab !== "history") return;
    Promise.all([api("/interview/history"), api("/interview/sessions")])
      .then(([h, s]) => { setHistory(h); setSessions(s.sessions); })
      .catch((e) => setErr(formatApiError(e.message, "Couldn't load history")));
  }, [tab]);

  async function createSession(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setErr("");
    try {
      const payload: any = {
        interview_type: interviewType, difficulty, duration_minutes: durationMinutes,
        planned_question_count: questionCount, focus_skills: focusSkills || null,
        target_role: targetRole || null, experience_level: experienceLevel,
      };
      if (interviewType === "job_specific" && jobId) payload.job_id = Number(jobId);
      if (interviewType === "coding") payload.programming_language = programmingLanguage;
      const session = await api("/interview/sessions", { method: "POST", body: JSON.stringify(payload) });
      router.push(`/interview/${session.id}`);
    } catch (e: any) {
      setErr(formatApiError(e.message, "Couldn't start this interview"));
    } finally {
      setCreating(false);
    }
  }

  return (
    <main className="container page">
      <div className="pagehead">
        <div>
          <span className="eyebrow">AI career copilot</span>
          <h1>Mock Interview</h1>
        </div>
        <div className="actions">
          <Link href="/career-copilot" className="btn secondary">Career Copilot</Link>
        </div>
      </div>

      <div className="filters">
        <button className={`chip ${tab === "setup" ? "chip-active" : ""}`} onClick={() => setTab("setup")}>Start new interview</button>
        <button className={`chip ${tab === "history" ? "chip-active" : ""}`} onClick={() => setTab("history")}>History</button>
      </div>

      {err && <p className="error">{err}</p>}

      {tab === "setup" && (
        <form className="form" onSubmit={createSession} style={{ marginTop: 20 }}>
          <label className="field-label">
            Interview type
            <select className="field" value={interviewType} onChange={(e) => setInterviewType(e.target.value)}>
              {INTERVIEW_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </label>

          {interviewType === "job_specific" && (
            <label className="field-label">
              Job ID (from a job listing you're interested in)
              <input className="field" value={jobId} onChange={(e) => setJobId(e.target.value)} placeholder="e.g. 42" required />
            </label>
          )}

          <div className="grid2">
            <label className="field-label">
              Target role (optional)
              <input className="field" value={targetRole} onChange={(e) => setTargetRole(e.target.value)} placeholder="e.g. Backend Engineer" />
            </label>
            <label className="field-label">
              Experience level
              <select className="field" value={experienceLevel} onChange={(e) => setExperienceLevel(e.target.value)}>
                {EXPERIENCE_LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </label>
          </div>

          <div className="grid2">
            <label className="field-label">
              Difficulty
              <select className="field" value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
                {DIFFICULTIES.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <label className="field-label">
              Duration (minutes)
              <input className="field" type="number" min={5} max={120} value={durationMinutes} onChange={(e) => setDurationMinutes(Number(e.target.value))} />
            </label>
          </div>

          <div className="grid2">
            <label className="field-label">
              Number of questions
              <input className="field" type="number" min={1} max={30} value={questionCount} onChange={(e) => setQuestionCount(Number(e.target.value))} />
            </label>
            <label className="field-label">
              Focus skills (comma-separated, optional)
              <input className="field" value={focusSkills} onChange={(e) => setFocusSkills(e.target.value)} placeholder="e.g. SQL, System Design" />
            </label>
          </div>

          {interviewType === "coding" && (
            <label className="field-label">
              Programming language
              <input className="field" value={programmingLanguage} onChange={(e) => setProgrammingLanguage(e.target.value)} placeholder="e.g. python" />
            </label>
          )}

          <div className="actions">
            <button className="btn" type="submit" disabled={creating}>{creating ? "Setting up…" : "Start interview"}</button>
          </div>
        </form>
      )}

      {tab === "history" && (
        <div style={{ marginTop: 20 }}>
          {history && (
            <>
              <div className="metrics">
                <div className="metric"><b>{history.past_interviews.length}</b><span>Completed interviews</span></div>
                <div className="metric"><b>{history.score_trend.at(-1) ?? "—"}</b><span>Most recent score</span></div>
                <div className="metric"><b>{history.strong_topics.length}</b><span>Strong topics</span></div>
              </div>
              {(history.strong_topics.length > 0 || history.weak_topics.length > 0) && (
                <div className="card" style={{ marginTop: 18 }}>
                  <h2>Topic breakdown</h2>
                  <div className="tagrow">
                    {history.strong_topics.map((t: string) => <span key={t} className="tag" style={{ background: "var(--good-wash)", color: "var(--good)" }}>{t}</span>)}
                    {history.weak_topics.map((t: string) => <span key={t} className="tag" style={{ background: "var(--bad-wash)", color: "var(--bad)" }}>{t}</span>)}
                  </div>
                </div>
              )}
            </>
          )}

          <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 18 }}>
            {sessions.map((s) => (
              <div className="card row" key={s.id}>
                <div>
                  <span className="pill">{s.interview_type.replace("_", " ")}</span>
                  <span className={`badge badge-${s.status === "completed" ? "active" : s.status === "cancelled" ? "disabled" : "paused"}`} style={{ marginLeft: 8 }}>{s.status}</span>
                  <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>{s.target_role || "General"} · {s.difficulty} · {new Date(s.created_at).toLocaleDateString()}</div>
                </div>
                <Link className="linkbtn" href={s.status === "completed" ? `/interview/${s.id}/report` : `/interview/${s.id}`}>
                  {s.status === "completed" ? "View report" : s.status === "in_progress" || s.status === "paused" ? "Continue" : "Open"}
                </Link>
              </div>
            ))}
          </div>
          {!sessions.length && <div className="empty">No interviews yet — start one above.</div>}
        </div>
      )}
    </main>
  );
}
