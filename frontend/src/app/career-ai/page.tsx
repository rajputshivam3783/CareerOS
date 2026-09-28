"use client";
import { safeHref } from "@/lib/safe";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

function VerdictPill({ eligible }: { eligible: boolean | null }) {
  const label = eligible === true ? "Likely eligible" : eligible === false ? "Not eligible" : "Unclear — verify manually";
  const cls = eligible === true ? "verified" : eligible === false ? "error" : "pill";
  return <span className={cls}>{label}</span>;
}

export default function Page() {
  const [id, setId] = useState("");
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => { setId(new URLSearchParams(window.location.search).get("job") || ""); }, []);
  const [examPrep, setExamPrep] = useState<any[] | null>(null);

  async function analyze() {
    setErr("");
    setLoading(true);
    setExamPrep(null);
    try {
      setRes(await api(`/career-ai/${id}`));
    } catch (e: any) {
      setErr(e.message);
      setRes(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadExamPrep() {
    try {
      setExamPrep(await api(`/jobs/${id}/exam-prep`));
    } catch {
      setExamPrep([]);
    }
  }

  return (
    <main className="container page">
      <span className="eyebrow">Career intelligence</span>
      <h1>Career AI</h1>
      <p className="muted">
        Enter a published Job ID from the Jobs page for a combined eligibility, match, and skill-gap
        analysis — plus a plain-language summary.
      </p>

      <div className="card form">
        <input className="field" type="number" placeholder="Job ID" value={id} onChange={(e) => setId(e.target.value)} />
        <button className="btn" onClick={analyze} disabled={!id || loading}>
          {loading ? "Analyzing…" : "Analyze"}
        </button>
      </div>

      {err && <p className="error">{err}</p>}

      {res && (
        <div className="card" style={{ marginTop: 20 }}>
          <h2>{res.job.title}</h2>
          <p className="strong">{res.job.organization}</p>

          <div className="row" style={{ margin: "12px 0" }}>
            <VerdictPill eligible={res.eligibility.eligible} />
            <span className="pill">Match: {res.match.score}/100</span>
          </div>

          <p>{res.advice.advice}</p>
          {res.advice.source === "template" && (
            <p className="muted">Rule-based summary — set CAREER_AI_ANTHROPIC_API_KEY for AI-narrated advice.</p>
          )}

          <h3>Why</h3>
          <ul>
            {res.eligibility.reasons?.map((r: string, i: number) => (
              <li key={i}>{r}</li>
            ))}
          </ul>

          {res.skill_gap.learn?.length > 0 && (
            <>
              <h3>Skills to build</h3>
              <ul>
                {res.skill_gap.learn.map((s: string, i: number) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </>
          )}

          <p className="muted">{res.eligibility.disclaimer}</p>

          <div className="actions" style={{ marginTop: 12 }}>
            <button className="btn secondary" onClick={loadExamPrep}>
              Load exam-prep resources
            </button>
            <a className="btn secondary" href="/resume">
              Match my resume instead
            </a>
          </div>

          {examPrep && (
            <div style={{ marginTop: 16 }}>
              <h3>Exam prep</h3>
              {examPrep.length === 0 && <p className="muted">No curated resources yet for this job.</p>}
              <ul>
                {examPrep.map((r: any) => (
                  <li key={r.id}>
                    <span className="pill">{r.resource_type}</span>{" "}
                    <a href={safeHref(r.url)} target="_blank" rel="noreferrer">
                      {r.title}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
