"use client";
// V20.4 — Live interview session. Handles setup->in_progress->paused
// cycles and hands off to the inline report view once the session
// completes (no separate navigation needed at that point, but
// /interview/[id]/report also exists as a direct link from history).
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, formatApiError } from "@/lib/api";
import ReportView from "../ReportView";

export default function InterviewSessionPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.id as string;

  const [session, setSession] = useState<any>(null);
  const [question, setQuestion] = useState<any>(null);
  const [answer, setAnswer] = useState("");
  const [code, setCode] = useState("");
  const [lastEvaluation, setLastEvaluation] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function load() {
    try {
      const list = await api("/interview/sessions");
      const s = list.sessions.find((x: any) => String(x.id) === sessionId);
      if (!s) { setErr("Interview session not found."); return; }
      setSession(s);
      if (s.status === "in_progress" || s.status === "paused") {
        try {
          const q = await api(`/interview/sessions/${sessionId}/current-question`);
          setQuestion(q);
        } catch { /* not started yet */ }
      } else if (s.status === "completed") {
        const r = await api(`/interview/sessions/${sessionId}/report`);
        setReport(r);
      }
    } catch (e: any) {
      setErr(formatApiError(e.message, "Couldn't load this interview"));
    }
  }

  useEffect(() => { load(); }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (session?.status === "in_progress") {
      timerRef.current = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);
    } else if (timerRef.current) {
      clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [session?.status]);

  async function start() {
    setBusy(true); setErr("");
    try {
      const resp = await api(`/interview/sessions/${sessionId}/start`, { method: "POST" });
      setSession(resp.session);
      setQuestion(resp.question);
    } catch (e: any) {
      setErr(formatApiError(e.message, "Couldn't start the interview"));
    } finally { setBusy(false); }
  }

  async function pause() {
    const s = await api(`/interview/sessions/${sessionId}/pause`, { method: "POST" });
    setSession((prev: any) => ({ ...prev, status: s.status }));
  }
  async function resume() {
    const s = await api(`/interview/sessions/${sessionId}/resume`, { method: "POST" });
    setSession((prev: any) => ({ ...prev, status: s.status }));
  }
  async function cancel() {
    if (!confirm("End this interview now? You can view a report for what you've answered so far.")) return;
    await api(`/interview/sessions/${sessionId}/cancel`, { method: "POST" });
    router.push("/interview");
  }

  async function submitAnswer(skip = false) {
    setBusy(true); setErr("");
    try {
      if (session.interview_type === "coding" && code.trim() && !skip) {
        await api(`/interview/sessions/${sessionId}/coding-submit`, {
          method: "POST", body: JSON.stringify({ language: session.programming_language || "python", code_text: code }),
        });
      }
      const answerText = session.interview_type === "coding" && code.trim() ? code : answer;
      const resp = await api(`/interview/sessions/${sessionId}/answer`, {
        method: "POST", body: JSON.stringify({ answer_text: skip ? "" : answerText, skip }),
      });
      setLastEvaluation(resp.evaluation);
      setAnswer(""); setCode("");
      if (resp.report) {
        setReport(resp.report);
        setSession((prev: any) => ({ ...prev, status: "completed" }));
      } else if (resp.next_question) {
        setQuestion(resp.next_question);
      }
    } catch (e: any) {
      setErr(formatApiError(e.message, "Couldn't submit that answer"));
    } finally { setBusy(false); }
  }

  if (err && !session) return <main className="container page"><p className="error">{err}</p></main>;
  if (!session) return <main className="container page"><p className="muted">Loading…</p></main>;

  if (report) {
    return (
      <main className="container page">
        <ReportView report={report} sessionId={sessionId} />
      </main>
    );
  }

  const progressPct = session.planned_question_count
    ? Math.min(100, Math.round((session.current_question_index / session.planned_question_count) * 100))
    : 0;
  const mm = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
  const ss = String(elapsedSeconds % 60).padStart(2, "0");

  return (
    <main className="container page">
      <div className="pagehead">
        <div>
          <span className="eyebrow">{session.interview_type.replace("_", " ")} interview</span>
          <h1 style={{ fontSize: 30 }}>{session.target_role || "Mock Interview"}</h1>
        </div>
        <div className="actions">
          {session.status === "in_progress" && <span className="pill">⏱ {mm}:{ss}</span>}
          <span className={`badge badge-${session.status === "in_progress" ? "active" : session.status === "paused" ? "paused" : "disabled"}`}>{session.status}</span>
        </div>
      </div>

      {session.planned_question_count > 0 && (
        <div className="steps" aria-label="Interview progress">
          {Array.from({ length: session.planned_question_count }).map((_, i) => (
            <span key={i} className={`step ${i < session.current_question_index ? "step-done" : i === session.current_question_index ? "step-active" : ""}`}>{i + 1}</span>
          ))}
        </div>
      )}

      {err && <p className="error">{err}</p>}

      {session.status === "ready" && (
        <div className="card">
          <h2>Ready to begin</h2>
          <p className="muted">You'll be asked {session.planned_question_count} question(s) at {session.difficulty} difficulty. Take your time — answers are evaluated for correctness, depth, clarity, and structure.</p>
          <div className="actions"><button className="btn" onClick={start} disabled={busy}>{busy ? "Starting…" : "Begin interview"}</button></div>
        </div>
      )}

      {session.status === "paused" && (
        <div className="card">
          <h2>Paused</h2>
          <p className="muted">Your progress is saved. Resume whenever you're ready.</p>
          <div className="actions"><button className="btn" onClick={resume}>Resume</button></div>
        </div>
      )}

      {(session.status === "in_progress") && question && (
        <div className="card">
          <div className="row">
            <span className="pill">{question.category.replace("_", " ")} · {question.difficulty}</span>
            {question.is_followup && <span className="verified">Follow-up</span>}
          </div>
          <h2 style={{ fontSize: 20, marginTop: 12 }}>{question.question_text}</h2>

          {lastEvaluation && (
            <div className="result" style={{ marginTop: 4, marginBottom: 16 }}>
              <b>Previous answer — {lastEvaluation.overall_score}/100</b>
              {"\n"}{lastEvaluation.explanation}
              {lastEvaluation.improvement_tips?.length > 0 && "\n\nTip: " + lastEvaluation.improvement_tips[0]}
            </div>
          )}

          {session.interview_type === "coding" ? (
            <textarea className="field" rows={12} style={{ fontFamily: "ui-monospace,monospace" }}
              placeholder={`// Write your solution in ${session.programming_language || "your language of choice"}`}
              value={code} onChange={(e) => setCode(e.target.value)} />
          ) : (
            <textarea className="field" rows={8} placeholder="Type your answer here…" value={answer} onChange={(e) => setAnswer(e.target.value)} />
          )}

          <div className="actions" style={{ marginTop: 14 }}>
            <button className="btn" onClick={() => submitAnswer(false)} disabled={busy || (!answer.trim() && !code.trim())}>
              {busy ? "Evaluating…" : "Submit answer"}
            </button>
            <button className="btn secondary" onClick={() => submitAnswer(true)} disabled={busy}>Skip</button>
            <button className="linkbtn" onClick={pause}>Pause</button>
            <button className="linkbtn danger" onClick={cancel}>End interview</button>
          </div>
        </div>
      )}

      {(session.status === "cancelled") && (
        <div className="empty">
          This interview was ended early. <Link href="/interview" className="linkbtn">Start a new one</Link>
        </div>
      )}
    </main>
  );
}
