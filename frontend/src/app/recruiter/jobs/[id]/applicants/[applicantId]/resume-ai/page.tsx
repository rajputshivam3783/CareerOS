"use client";
// V20.2 — AI Resume Intelligence, recruiter view. Deliberately its own
// route rather than an edit to the existing applicant detail page
// (frontend/src/app/recruiter/jobs/[id]/applicants/[applicantId]/page.tsx)
// — that page is part of the V18 ATS architecture and is left untouched;
// this is purely additive, linked to from there manually if desired.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, formatApiError } from "@/lib/api";

export default function RecruiterApplicantResumeAI() {
  const { id, applicantId } = useParams<{ id: string; applicantId: string }>();
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        setData(await api(`/resume-ai/applicant/${applicantId}/analysis`));
      } catch (e: any) {
        setErr(formatApiError(e.message, e.message));
      }
    })();
  }, [applicantId]);

  return (
    <main className="container page">
      <span className="eyebrow">AI resume intelligence — recruiter view</span>
      <h1>Applicant resume analysis</h1>
      <p className="muted">
        Based on the resume snapshot captured when this candidate applied — not their live, possibly-updated
        resume. <a href={`/recruiter/jobs/${id}/applicants/${applicantId}`}>← Back to applicant</a>
      </p>
      {err && <p className="error">{err}</p>}
      {!data && !err && <p className="muted">Loading...</p>}

      {data && (
        <>
          <div className="card" style={{ marginTop: 18 }}>
            <h2>Resume quality: {data.scores.overall.score}/100</h2>
            <ul className="muted" style={{ fontSize: 13 }}>{data.scores.overall.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
          </div>

          <div className="card" style={{ marginTop: 18 }}>
            <h2>Match against this job: {data.match.overall}%</h2>
            <p className="muted" style={{ fontSize: 13 }}>{data.match.skills.explanation}</p>
            <p className="muted" style={{ fontSize: 13 }}>{data.match.experience.explanation}</p>
            <p className="muted" style={{ fontSize: 13 }}>{data.match.education.explanation}</p>
            <p className="muted" style={{ fontSize: 13 }}>{data.match.keywords.explanation}</p>
          </div>

          <div className="card" style={{ marginTop: 18 }}>
            <h2>Skill gap</h2>
            <p><b>Matched:</b> {data.skill_gap.matched_skills.join(", ") || "none"}</p>
            <p><b>Missing:</b> {data.skill_gap.missing_skills.join(", ") || "none"}</p>
            <p><b>Weak:</b> {data.skill_gap.weak_skills.join(", ") || "none"}</p>
          </div>
        </>
      )}
    </main>
  );
}
