"use client";
// V20.4 — shared between app/interview/[id]/page.tsx (inline, right
// after finishing) and app/interview/[id]/report/page.tsx (direct
// link from history) so the report is defined once.
import { useState } from "react";
import Link from "next/link";
import { api, formatApiError } from "@/lib/api";

const SCORE_LABELS: Record<string, string> = {
  overall_score: "Overall", technical_score: "Technical", communication_score: "Communication",
  problem_solving_score: "Problem Solving", role_fit_score: "Role Fit", confidence_score: "Confidence",
};

export default function ReportView({ report, sessionId }: { report: any; sessionId: string }) {
  const [explanation, setExplanation] = useState("");
  const [explaining, setExplaining] = useState(false);
  const [err, setErr] = useState("");
  const [questions, setQuestions] = useState<any[] | null>(null);

  async function explainWithCopilot() {
    setExplaining(true); setErr("");
    try {
      const resp = await api(`/interview/sessions/${sessionId}/report/explain`, { method: "POST" });
      setExplanation(resp.explanation);
    } catch (e: any) {
      setErr(formatApiError(e.message, "Couldn't get an explanation right now"));
    } finally { setExplaining(false); }
  }

  async function loadQuestions() {
    const resp = await api(`/interview/sessions/${sessionId}/questions`);
    setQuestions(resp.questions);
  }

  return (
    <div>
      <div className="pagehead">
        <div>
          <span className="eyebrow">Interview report</span>
          <h1 style={{ fontSize: 32 }}>Overall score: {report.overall_score}/100</h1>
        </div>
        <Link href="/interview" className="btn secondary">Back to interviews</Link>
      </div>

      <div className="statgrid">
        {Object.keys(SCORE_LABELS).filter((k) => k !== "overall_score").map((k) => (
          <div className="statcard" key={k}><b>{report[k]}</b><span>{SCORE_LABELS[k]}</span></div>
        ))}
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <h2>Summary</h2>
        <p>{report.summary}</p>
      </div>

      <div className="grid2" style={{ marginTop: 18 }}>
        <div className="card">
          <h2>Strengths</h2>
          <ul>{report.strengths.map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>
          {!report.strengths.length && <p className="muted">None recorded for this session.</p>}
        </div>
        <div className="card">
          <h2>Weaknesses</h2>
          <ul>{report.weaknesses.map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>
          {!report.weaknesses.length && <p className="muted">None recorded for this session.</p>}
        </div>
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <h2>Communication feedback</h2>
        <p>{report.communication_feedback}</p>
      </div>

      {report.technical_gaps.length > 0 && (
        <div className="card" style={{ marginTop: 18 }}>
          <h2>Technical gaps</h2>
          <div className="tagrow">{report.technical_gaps.map((g: string, i: number) => <span className="tag" key={i}>{g}</span>)}</div>
        </div>
      )}

      <div className="grid2" style={{ marginTop: 18 }}>
        <div className="card">
          <h2>Recommended topics</h2>
          <ul>{report.recommended_topics.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul>
        </div>
        <div className="card">
          <h2>Next steps</h2>
          <ul>{report.next_steps.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul>
        </div>
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <div className="row">
          <h2>Ask the Career Copilot to explain this</h2>
          <button className="btn secondary" onClick={explainWithCopilot} disabled={explaining}>
            {explaining ? "Thinking…" : explanation ? "Regenerate" : "Explain my report"}
          </button>
        </div>
        {err && <p className="error">{err}</p>}
        {explanation && <p style={{ whiteSpace: "pre-wrap", marginTop: 10 }}>{explanation}</p>}
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <div className="row">
          <h2>Question-by-question breakdown</h2>
          {!questions && <button className="linkbtn" onClick={loadQuestions}>Show details</button>}
        </div>
        {questions && (
          <div className="jobs" style={{ gridTemplateColumns: "1fr", marginTop: 10 }}>
            {questions.map((q: any) => (
              <div className="card" key={q.id} style={{ background: "var(--paper)" }}>
                <span className="pill">{q.category.replace("_", " ")} · {q.difficulty}</span>
                {q.is_followup && <span className="verified" style={{ marginLeft: 8 }}>Follow-up</span>}
                <p style={{ marginTop: 8, fontWeight: 700 }}>{q.question_text}</p>
                {q.answer && <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{q.answer.skipped ? "(skipped)" : q.answer.answer_text}</p>}
                {q.evaluation && <p style={{ marginTop: 6 }}><b>{q.evaluation.overall_score}/100</b> — {q.evaluation.explanation}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
