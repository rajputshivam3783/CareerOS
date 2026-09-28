"use client";
import { useEffect, useState } from "react";
import { fetchSavedJobIds, isSignedIn, toggleBookmark } from "@/lib/bookmarks";
import { shareOrCopy } from "@/lib/share";

export default function GovHomeClient({ initialLatest, initialClosingSoon }: { initialLatest: any[]; initialClosingSoon: any[] }) {
  const [saved, setSaved] = useState<Set<number>>(new Set());

  useEffect(() => { if (isSignedIn()) fetchSavedJobIds().then(setSaved); }, []);

  async function onBookmark(jobId: number) {
    if (!isSignedIn()) { alert("Sign in to save recruitments."); return; }
    const nowSaved = await toggleBookmark(jobId, saved.has(jobId));
    setSaved(prev => { const next = new Set(prev); nowSaved ? next.add(jobId) : next.delete(jobId); return next; });
  }

  function onShare(job: any) {
    const url = typeof window !== "undefined" ? `${window.location.origin}/jobs/${job.id}` : `/jobs/${job.id}`;
    shareOrCopy(job.title, url);
  }

  function List({ title, jobs }: { title: string; jobs: any[] }) {
    if (!jobs.length) return null;
    return (
      <>
        <h2>{title}</h2>
        <div className="jobs">
          {jobs.slice(0, 6).map(job => (
            <article className="card" key={job.id}>
              <h2><a href={`/jobs/${job.id}`}>{job.title}</a></h2>
              <p className="strong">{job.organization}</p>
              {job.deadline && <p>Deadline: <b>{job.deadline}</b></p>}
              <div className="actions">
                <a className="btn secondary" href={`/jobs/${job.id}`}>View details</a>
                <button className="btn secondary" onClick={() => onBookmark(job.id)}>{saved.has(job.id) ? "Saved ✓" : "Save"}</button>
                <button className="btn secondary" onClick={() => onShare(job)}>Share</button>
              </div>
            </article>
          ))}
        </div>
      </>
    );
  }

  return (
    <>
      <List title="Latest jobs" jobs={initialLatest} />
      <List title="Closing soon" jobs={initialClosingSoon} />
    </>
  );
}
