"use client";

import { useEffect, useState, useCallback, FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

type Candidate = {
  id: number;
  full_name: string;
  headline: string | null;
  top_skills: string[];
  experience_level: string | null;
  location: string | null;
  education: string | null;
  has_resume: boolean;
  profile_completeness: number;
  discoverable_via: "application" | "opted_in";
  applications: { applicant_id: number; job_id: number; status: string; pipeline_stage: string | null }[];
  actions: { can_shortlist: boolean; shortlist_applicant_id: number | null; can_view_application: boolean };
  match_score?: number;
  match_reasons?: string[];
};

const PAGE_SIZE = 20;

export default function CandidatesClient() {
  const params = useSearchParams();
  const jobId = params.get("job_id");

  const [q, setQ] = useState("");
  const [skills, setSkills] = useState("");
  const [skillsMode, setSkillsMode] = useState<"any" | "all">("any");
  const [location, setLocation] = useState("");
  const [education, setEducation] = useState("");
  const [minExp, setMinExp] = useState("");
  const [maxExp, setMaxExp] = useState("");
  const [resumeOnly, setResumeOnly] = useState(false);
  const [sortBy, setSortBy] = useState("profile_completeness");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);

  const [items, setItems] = useState<Candidate[]>([]);
  const [total, setTotal] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      if (jobId) {
        const res = await api(`/recruiter/jobs/${jobId}/candidate-matches?page=${page}&page_size=${PAGE_SIZE}`);
        setItems(res.items);
        setTotal(res.total);
        setTruncated(!!res.truncated);
      } else {
        const qs = new URLSearchParams();
        if (q) qs.set("q", q);
        skills
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
          .forEach((s) => qs.append("skills", s));
        if (skills.trim()) qs.set("skills_mode", skillsMode);
        if (location) qs.set("location", location);
        if (education) qs.set("education", education);
        if (minExp) qs.set("min_experience_years", minExp);
        if (maxExp) qs.set("max_experience_years", maxExp);
        if (resumeOnly) qs.set("resume_available", "true");
        qs.set("sort_by", sortBy);
        qs.set("sort_dir", sortDir);
        qs.set("page", String(page));
        qs.set("page_size", String(PAGE_SIZE));
        const res = await api(`/recruiter/candidates?${qs.toString()}`);
        setItems(res.items);
        setTotal(res.total);
        setTruncated(false);
      }
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [jobId, q, skills, skillsMode, location, education, minExp, maxExp, resumeOnly, sortBy, sortDir, page]);

  useEffect(() => {
    load();
  }, [load]);

  function applyFilters(e: FormEvent) {
    e.preventDefault();
    setPage(1);
    load();
  }

  async function shortlist(applicantId: number) {
    setBusyId(applicantId);
    try {
      await api(`/recruiter/applicants/${applicantId}/stage`, {
        method: "PATCH",
        body: JSON.stringify({ pipeline_stage: "shortlisted" }),
      });
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusyId(null);
    }
  }

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <main className="container page">
      <span className="eyebrow">Candidate discovery</span>
      <div className="pagehead">
        <div>
          <h1>{jobId ? "Find candidates for this job" : "Find candidates"}</h1>
          <p className="muted">
            {jobId
              ? "Ranked by fit against this job's title, skills, experience, education and location."
              : "Candidates who applied to your jobs, plus candidates who've opted in to recruiter discovery."}
          </p>
        </div>
        <a className="btn secondary" href="/recruiter/jobs">Back to jobs</a>
      </div>

      {!jobId && (
        <details className="card section" open>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Search &amp; filters</summary>
          <form className="grid2" onSubmit={applyFilters} style={{ marginTop: 12 }}>
            <label className="field-label">
              Keyword
              <input className="field" placeholder="Name, skill, headline, location…" value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
            <label className="field-label">
              Skills (comma-separated)
              <input className="field" placeholder="Java, Spring Boot, SQL" value={skills} onChange={(e) => setSkills(e.target.value)} />
            </label>
            <label className="field-label">
              Skill match
              <select className="field" value={skillsMode} onChange={(e) => setSkillsMode(e.target.value as "any" | "all")}>
                <option value="any">Any selected skill</option>
                <option value="all">All selected skills</option>
              </select>
            </label>
            <label className="field-label">
              Location
              <input className="field" value={location} onChange={(e) => setLocation(e.target.value)} />
            </label>
            <label className="field-label">
              Education contains
              <input className="field" value={education} onChange={(e) => setEducation(e.target.value)} />
            </label>
            <label className="field-label">
              Experience (years)
              <div className="row">
                <input className="field" type="number" min={0} placeholder="Min" value={minExp} onChange={(e) => setMinExp(e.target.value)} />
                <input className="field" type="number" min={0} placeholder="Max" value={maxExp} onChange={(e) => setMaxExp(e.target.value)} />
              </div>
            </label>
            <label className="field-label">
              Sort by
              <select className="field" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="profile_completeness">Profile completeness</option>
                <option value="experience">Experience</option>
                <option value="recently_active">Recently active</option>
                <option value="name">Name</option>
              </select>
            </label>
            <label className="field-label">
              Order
              <select className="field" value={sortDir} onChange={(e) => setSortDir(e.target.value as "asc" | "desc")}>
                <option value="desc">Highest first</option>
                <option value="asc">Lowest first</option>
              </select>
            </label>
            <label className="checkbox-label">
              <input type="checkbox" checked={resumeOnly} onChange={(e) => setResumeOnly(e.target.checked)} />
              Resume on file only
            </label>
            <button className="btn" type="submit">Apply filters</button>
          </form>
        </details>
      )}

      {truncated && <p className="muted">Showing a bounded top slice of a very large discoverable pool for this job.</p>}

      <div aria-live="polite" className="muted" style={{ margin: "12px 0" }}>
        {loading ? "Searching…" : `${total} candidate${total === 1 ? "" : "s"} found`}
      </div>

      {err && <p className="error">{err}</p>}

      {!loading && !err && items.length === 0 && (
        <div className="card">
          <p className="muted">
            No candidates match yet. Candidates only appear here once they've applied to one of your jobs, or opted in to
            recruiter discovery from their own profile.
          </p>
        </div>
      )}

      <div className="list">
        {items.map((c) => (
          <div className="card" key={c.id}>
            <div className="row">
              <h2 style={{ margin: 0 }}>{c.full_name}</h2>
              {typeof c.match_score === "number" && <span className="pill">Match: {c.match_score}%</span>}
              <span className="pill">{c.discoverable_via === "application" ? "Applied" : "Opted in"}</span>
            </div>
            {c.headline && <p className="strong">{c.headline}</p>}
            <p className="muted">
              {c.location || "Location not set"} · {c.experience_level || "Experience not stated"} ·{" "}
              {c.education || "Education not stated"}
            </p>
            {c.top_skills.length > 0 && <p className="muted">Skills: {c.top_skills.join(", ")}</p>}
            <p className="muted">Profile completeness: {c.profile_completeness}%{c.has_resume ? " · Resume on file" : ""}</p>
            {c.match_reasons && c.match_reasons.length > 0 && (
              <ul aria-label="Why this candidate matches">
                {c.match_reasons.map((r, i) => (
                  <li key={i} className="muted">{r}</li>
                ))}
              </ul>
            )}
            <div className="jobcard-actions">
              <a className="linkbtn" href={`/recruiter/candidates/${c.id}`}>View profile</a>
              {c.actions.can_view_application && c.applications[0] && (
                <a className="linkbtn" href={`/recruiter/jobs/${c.applications[0].job_id}/pipeline`}>View application</a>
              )}
              {c.actions.can_shortlist && c.actions.shortlist_applicant_id && (
                <button
                  className="linkbtn"
                  disabled={busyId === c.actions.shortlist_applicant_id}
                  onClick={() => shortlist(c.actions.shortlist_applicant_id as number)}
                >
                  Shortlist
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {pageCount > 1 && (
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn secondary" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
            Previous
          </button>
          <span className="muted">
            Page {page} of {pageCount}
          </span>
          <button className="btn secondary" disabled={page >= pageCount} onClick={() => setPage((p) => Math.min(pageCount, p + 1))}>
            Next
          </button>
        </div>
      )}
    </main>
  );
}
