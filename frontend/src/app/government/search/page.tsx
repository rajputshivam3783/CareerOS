"use client";
import { safeHref } from "@/lib/safe";
import { useEffect, useState } from "react";
import { API } from "@/lib/api";
import Breadcrumbs from "@/components/Breadcrumbs";
import { SkeletonCards } from "@/components/Skeleton";
import { fetchSavedJobIds, isSignedIn, toggleBookmark } from "@/lib/bookmarks";
import { shareOrCopy } from "@/lib/share";

export default function Page() {
  const [organization, setOrganization] = useState("");
  const [exam, setExam] = useState("");
  const [post, setPost] = useState("");
  const [qualification, setQualification] = useState("");
  const [location, setLocation] = useState("");
  const [adNumber, setAdNumber] = useState("");

  const [results, setResults] = useState<any[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [total, setTotal] = useState<number | null>(null);
  const [saved, setSaved] = useState<Set<number>>(new Set());

  useEffect(() => { if (isSignedIn()) fetchSavedJobIds().then(setSaved); }, []);

  async function search() {
    setLoading(true); setError(""); setSearched(true);
    try {
      const params = new URLSearchParams();
      if (organization) params.set("organization", organization);
      if (exam) params.set("exam", exam);
      if (post) params.set("post", post);
      if (qualification) params.set("qualification", qualification);
      if (location) params.set("location", location);
      if (adNumber) params.set("ad_number", adNumber);
      const r = await fetch(`${API}/government/search?${params.toString()}`);
      if (!r.ok) throw new Error("Search failed — please try again.");
      setResults(await r.json());
      const totalHeader = r.headers.get("X-Total-Count");
      setTotal(totalHeader ? parseInt(totalHeader, 10) : null);
    } catch (e: any) {
      setError(e.message);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  async function onBookmark(jobId: number) {
    if (!isSignedIn()) { alert("Sign in to save recruitments."); return; }
    const nowSaved = await toggleBookmark(jobId, saved.has(jobId));
    setSaved(prev => { const next = new Set(prev); nowSaved ? next.add(jobId) : next.delete(jobId); return next; });
  }

  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Advanced Search" }]} />
      <span className="eyebrow">Government portal</span>
      <h1>Advanced search</h1>
      <p className="muted">Search across every published government recruitment by organization, exam, post, qualification, location or advertisement number.</p>

      <div className="card form">
        <input className="field" placeholder="Organization (e.g. SSC, UPSC, SBI)" value={organization} onChange={e => setOrganization(e.target.value)} onKeyDown={e => e.key === "Enter" && search()} />
        <input className="field" placeholder="Exam name" value={exam} onChange={e => setExam(e.target.value)} onKeyDown={e => e.key === "Enter" && search()} />
        <input className="field" placeholder="Post / title" value={post} onChange={e => setPost(e.target.value)} onKeyDown={e => e.key === "Enter" && search()} />
        <input className="field" placeholder="Qualification" value={qualification} onChange={e => setQualification(e.target.value)} onKeyDown={e => e.key === "Enter" && search()} />
        <input className="field" placeholder="Location" value={location} onChange={e => setLocation(e.target.value)} onKeyDown={e => e.key === "Enter" && search()} />
        <input className="field" placeholder="Advertisement number" value={adNumber} onChange={e => setAdNumber(e.target.value)} onKeyDown={e => e.key === "Enter" && search()} />
        <button className="btn" onClick={search}>Search</button>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <SkeletonCards />}
      {!loading && searched && total !== null && <p className="muted">{total} {total === 1 ? "result" : "results"}</p>}
      {!loading && searched && !results.length && !error && (
        <div className="empty">No published recruitments match this search yet — results only ever come from ingested adapter data.</div>
      )}

      <div className="jobs">
        {results.map(job => (
          <article className="card" key={job.id}>
            <h2><a href={`/jobs/${job.id}`}>{job.title}</a></h2>
            <p className="strong">{job.organization}</p>
            {job.location && <p>{job.location}{job.vacancies ? ` • ${job.vacancies} vacancies` : ""}</p>}
            {job.qualification && <p className="muted">{job.qualification}</p>}
            {job.ad_number && <p className="muted">Advt. No. {job.ad_number}</p>}
            {job.deadline && <p>Deadline: <b>{job.deadline}</b></p>}
            <div className="actions">
              <a className="btn secondary" href={`/jobs/${job.id}`}>View details</a>
              <button className="btn secondary" onClick={() => onBookmark(job.id)}>{saved.has(job.id) ? "Saved ✓" : "Save"}</button>
              <button className="btn secondary" onClick={() => shareOrCopy(job.title, `${window.location.origin}/jobs/${job.id}`)}>Share</button>
              {job.official_url && <a className="btn" href={safeHref(job.official_url)} target="_blank" rel="noreferrer">Official link</a>}
            </div>
          </article>
        ))}
      </div>
    </main>
  );
}
