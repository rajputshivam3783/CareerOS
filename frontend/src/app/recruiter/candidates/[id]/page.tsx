"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

export default function Page() {
  const params = useParams();
  const id = params?.id as string;
  const [c, setC] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        setC(await api(`/recruiter/candidates/${id}`));
      } catch (e: any) {
        setErr(e.message);
      }
    })();
  }, [id]);

  if (err) return <main className="container page"><p className="error">{err}</p></main>;
  if (!c) return <main className="container page">Loading…</main>;

  return (
    <main className="container page">
      <span className="eyebrow">Candidate profile</span>
      <div className="pagehead">
        <div>
          <h1>{c.full_name}</h1>
          {c.headline && <p className="muted">{c.headline}</p>}
        </div>
        <a className="btn secondary" href="/recruiter/candidates">Back to search</a>
      </div>

      <div className="card">
        <h2>Overview</h2>
        <p><b>Location:</b> {c.location || "Not stated"}</p>
        <p><b>Experience level:</b> {c.experience_level || "Not stated"}</p>
        <p><b>Education:</b> {c.education || "Not stated"}{c.graduation_year ? ` (${c.graduation_year})` : ""}</p>
        <p><b>Preferred roles:</b> {c.preferred_roles || "Not stated"}</p>
        <p><b>Preferred locations:</b> {c.preferred_locations || "Not stated"}</p>
        <p><b>Career goal:</b> {c.career_goal || "Not stated"}</p>
        <p><b>Profile completeness:</b> {c.profile_completeness}%</p>
      </div>

      {c.top_skills?.length > 0 && (
        <div className="card section">
          <h2>Skills</h2>
          <p>{c.top_skills.join(", ")}</p>
        </div>
      )}

      {c.applications?.length > 0 && (
        <div className="card section">
          <h2>Applications to your jobs</h2>
          {c.applications.map((a: any) => (
            <p key={a.applicant_id}>
              Job #{a.job_id} — {a.status} ({a.pipeline_stage || "applied"}){" "}
              <a className="linkbtn" href={`/recruiter/jobs/${a.job_id}/pipeline`}>Open pipeline</a>
            </p>
          ))}
        </div>
      )}

      <div className="card section">
        <h2>Resume</h2>
        {c.resume ? (
          <>
            <p className="muted">{c.resume.original_filename} — uploaded {new Date(c.resume.uploaded_at).toLocaleDateString()}</p>
            <pre style={{ whiteSpace: "pre-wrap" }}>{c.resume.extracted_text}</pre>
          </>
        ) : (
          <p className="muted">No resume on file.</p>
        )}
      </div>
    </main>
  );
}
