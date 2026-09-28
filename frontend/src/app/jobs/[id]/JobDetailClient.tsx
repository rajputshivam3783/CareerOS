"use client";
import { safeHref } from "@/lib/safe";
import { useEffect, useState } from "react";
import { API, api } from "@/lib/api";
import Breadcrumbs from "@/components/Breadcrumbs";
import { fetchSavedJobIds, isSignedIn, toggleBookmark } from "@/lib/bookmarks";
import { shareOrCopy } from "@/lib/share";
import { trackApplicationFromJob } from "@/lib/applications";

export default function JobDetailClient({ id, initialJob, initialTimeline }: { id: number; initialJob: any; initialTimeline: any[] }) {
  const [j, setJ] = useState<any>(initialJob);
  const [timeline, setTimeline] = useState<any[]>(initialTimeline);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [trackBusy, setTrackBusy] = useState(false);
  const [trackMsg, setTrackMsg] = useState("");

  useEffect(() => {
    if (j) return;
    fetch(`${API}/jobs/${id}`).then(async r => {
      if (!r.ok) throw new Error("Opportunity not found");
      setJ(await r.json());
    }).catch(e => setErr(e.message));
    fetch(`${API}/jobs/${id}/timeline`).then(r => r.ok ? r.json() : null).then(x => setTimeline(x?.updates || [])).catch(() => {});
  }, [id, j]);

  useEffect(() => {
    if (isSignedIn()) fetchSavedJobIds().then(ids => setSaved(ids.has(id)));
  }, [id]);

  async function save() {
    if (!isSignedIn()) { alert("Sign in to save recruitments."); return; }
    try {
      const nowSaved = await toggleBookmark(id, saved);
      setSaved(nowSaved);
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function apply() {
    try {
      await api(`/jobs/${id}/apply`, { method: "POST", body: "{}" });
      alert("Application submitted and added to your pipeline");
    } catch (e: any) {
      alert(e.message);
    }
  }

  // V22.1 — APPLY FROM CAREEROS JOB: adds this job to the candidate's
  // own private application tracker (@/lib/applications), separate
  // from the recruiter-visible pipeline `apply()` above creates.
  async function trackApplication(markApplied: boolean) {
    if (!isSignedIn()) { alert("Sign in to track this application."); return; }
    setTrackBusy(true);
    setTrackMsg("");
    try {
      await trackApplicationFromJob(id, markApplied);
      setTrackMsg(markApplied ? "Marked as applied — see it in My Applications." : "Added to My Applications.");
    } catch (e: any) {
      setTrackMsg(e.message || "Could not track this application.");
    } finally {
      setTrackBusy(false);
    }
  }

  function share() {
    shareOrCopy(j?.title || "Recruitment", typeof window !== "undefined" ? window.location.href : "", () => {
      setCopied(true); setTimeout(() => setCopied(false), 2000);
    });
  }

  if (err) return <main className="container page"><p className="error">{err}</p></main>;
  if (!j) return <main className="container page"><p className="muted">Loading…</p></main>;

  const isGovernment = j.job_type === "Government";

  return (
    <main className="container page">
      <Breadcrumbs items={[
        { label: isGovernment ? "Government Portal" : "Jobs", href: isGovernment ? "/government/latest-jobs" : "/jobs" },
        { label: j.title },
      ]} />
      <div className="detailgrid">
        <article>
          <span className="eyebrow">{j.job_type} opportunity</span>
          <h1>{j.title}</h1>
          <p className="strong">{j.organization}</p>
          <div className="actions">
            {j.verified && <span className="verified">Verified listing</span>}
            <span className="pill">{j.location}</span>
            {j.govt_level && <span className="pill">{j.govt_level}</span>}
            {j.category && <span className="pill">{j.category}</span>}
            {j.ad_number && <span className="pill">Advt. No. {j.ad_number}</span>}
          </div>

          <section className="card section">
            <h2>Overview</h2>
            <p>{j.description}</p>
          </section>

          <section className="card section">
            <h2>Important dates</h2>
            <div className="jobmeta">
              <span>Application deadline<b>{j.deadline || "See notification"}</b></span>
              <span>Exam date<b>{j.exam_date || "See notification"}</b></span>
              <span>Admit card<b>{j.admit_card_date || "See notification"}</b></span>
              <span>Result<b>{j.result_date || "See notification"}</b></span>
            </div>
          </section>

          <section className="card section">
            <h2>Vacancy details</h2>
            <div className="jobmeta">
              <span>Vacancies<b>{j.vacancies ?? "Not specified"}</b></span>
              <span>Salary / stipend<b>{j.salary || j.stipend || "See notification"}</b></span>
            </div>
          </section>

          <section className="card section">
            <h2>Eligibility</h2>
            <div className="jobmeta">
              <span>Qualification<b>{j.qualification || "See notification"}</b></span>
              <span>Age limit<b>{j.age_limit || "See notification"}</b></span>
            </div>
          </section>

          {j.application_fee && (
            <section className="card section">
              <h2>Application fee</h2>
              <p>{j.application_fee}</p>
            </section>
          )}

          {j.selection_process && (
            <section className="card section">
              <h2>Selection process</h2>
              <p>{j.selection_process}</p>
            </section>
          )}

          {isGovernment && (
            <section className="card section">
              <h2>Recruitment timeline</h2>
              {timeline.length === 0 ? <p className="muted">No lifecycle updates published yet.</p> : timeline.map((u: any) => (
                <div key={u.id}>
                  <b>{String(u.update_type).replaceAll("_", " ").toUpperCase()}</b>
                  <p>{u.title} {u.event_date ? `· ${u.event_date}` : ""} {u.source_url && <a target="_blank" rel="noreferrer" href={safeHref(u.source_url)}>Official link</a>}</p>
                </div>
              ))}
            </section>
          )}

          <section className="card section">
            <h2>Important links</h2>
            <div className="actions">
              {j.notification_url && <a className="btn secondary" target="_blank" rel="noreferrer" href={safeHref(j.notification_url)}>Official notification</a>}
              {j.official_url && <a className="btn secondary" target="_blank" rel="noreferrer" href={safeHref(j.official_url)}>Official website</a>}
              {j.admit_card_url && <a className="btn secondary" target="_blank" rel="noreferrer" href={safeHref(j.admit_card_url)}>Admit card</a>}
              {j.result_url && <a className="btn secondary" target="_blank" rel="noreferrer" href={safeHref(j.result_url)}>Result</a>}
            </div>
          </section>
        </article>

        <aside className="card stickycard">
          <h2>Take action</h2>
          <div className="form">
            <button className="btn secondary" onClick={save}>{saved ? "Saved ✓" : "Save opportunity"}</button>
            <button className="btn secondary" onClick={share}>{copied ? "Link copied!" : "Share"}</button>
            <a className="btn secondary" href={`/career-ai?job=${id}`}>Check eligibility & match</a>
            <a className="btn secondary" href={`/resume?job=${id}`}>Match my resume</a>
            {j.owner_user_id && <button className="btn" onClick={apply}>Apply through CareerOS</button>}
            {j.apply_url && <a className="btn" target="_blank" rel="noreferrer" href={safeHref(j.apply_url)}>Apply on official site</a>}
            <button className="btn secondary" onClick={() => trackApplication(false)} disabled={trackBusy}>Track Application</button>
            <button className="btn secondary" onClick={() => trackApplication(true)} disabled={trackBusy}>Mark as Applied</button>
            {trackMsg && <p className="muted" style={{ fontSize: 13 }}>{trackMsg} <a href="/applications">View My Applications →</a></p>}
            <p className="muted">Never pay anyone claiming to guarantee selection. Verify details on the official source.</p>
          </div>
        </aside>
      </div>
    </main>
  );
}
