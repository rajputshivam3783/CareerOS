"use client";
import { safeHref } from "@/lib/safe";
// V19.3 — Government Portal. One reusable browser component behind
// every section page (Latest Jobs, Results, Admit Cards, Answer Keys,
// Syllabus, Admissions, Scholarships, Counselling, Cutoffs, Merit
// Lists, Document Verification, Medical Examination, Final Selection,
// Joining, Cancelled Recruitments, Archive) instead of 16 bespoke
// implementations — each route file just supplies the section slug,
// title, and a couple of feature flags. All data comes from the
// existing V19.1/V19.3 `/government/sections/{section}` endpoint,
// which itself only ever returns adapter-ingested Job/RecruitmentUpdate
// rows — nothing here hardcodes a recruitment.
import { useEffect, useRef, useState } from "react";
import { API } from "@/lib/api";
import { fetchSavedJobIds, isSignedIn, toggleBookmark } from "@/lib/bookmarks";
import { shareOrCopy } from "@/lib/share";
import { SkeletonCards } from "@/components/Skeleton";

type Row = { update?: any; job: any };
const PAGE_SIZE = 20;
const SORTS: [string, string][] = [
  ["newest", "Newest"], ["deadline", "Closing soon"], ["vacancies", "Most vacancies"], ["organization", "Organization A–Z"],
];

export default function GovSectionBrowser({
  section, title, description, mode, allowInfiniteScroll = false, showAdvancedFilters = false,
}: {
  section: string; title: string; description?: string; mode: "jobs" | "updates";
  allowInfiniteScroll?: boolean; showAdvancedFilters?: boolean;
}) {
  const [view, setView] = useState<"cards" | "table">("cards");
  const [infinite, setInfinite] = useState(allowInfiniteScroll);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const [search, setSearch] = useState("");
  const [organization, setOrganization] = useState("");
  const [govtLevel, setGovtLevel] = useState("");
  const [category, setCategory] = useState("");
  const [qualification, setQualification] = useState("");
  const [location, setLocation] = useState("");
  const [adNumber, setAdNumber] = useState("");
  const [sort, setSort] = useState("newest");

  const [facets, setFacets] = useState<{ govt_levels: string[]; categories: string[] }>({ govt_levels: [], categories: [] });
  const [saved, setSaved] = useState<Set<number>>(new Set());
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetch(`${API}/government/filters`).then(r => r.json()).then(setFacets).catch(() => {});
    if (isSignedIn()) fetchSavedJobIds().then(setSaved);
  }, []);

  function buildParams(currentOffset: number) {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (organization) params.set("organization", organization);
    if (govtLevel) params.set("govt_level", govtLevel);
    if (category) params.set("category", category);
    if (qualification) params.set("qualification", qualification);
    if (location) params.set("location", location);
    if (adNumber) params.set("ad_number", adNumber);
    params.set("sort", sort);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(currentOffset));
    return params;
  }

  async function load(currentOffset: number, append: boolean) {
    append ? setLoadingMore(true) : setLoading(true);
    setError("");
    try {
      const r = await fetch(`${API}/government/sections/${section}?${buildParams(currentOffset)}`);
      if (!r.ok) throw new Error("Could not load this section right now.");
      const data = await r.json();
      const asRows: Row[] = mode === "updates" ? data : data.map((job: any) => ({ job }));
      setRows(prev => (append ? [...prev, ...asRows] : asRows));
      const totalHeader = r.headers.get("X-Total-Count");
      setTotal(totalHeader ? parseInt(totalHeader, 10) : null);
    } catch (e: any) {
      setError(e.message || "Something went wrong.");
      if (!append) setRows([]);
    } finally {
      append ? setLoadingMore(false) : setLoading(false);
    }
  }

  useEffect(() => { setOffset(0); load(0, false); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [section, sort]);

  useEffect(() => {
    if (!infinite) return;
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting && !loading && !loadingMore && total !== null && rows.length < total) {
        const next = offset + PAGE_SIZE;
        setOffset(next);
        load(next, true);
      }
    }, { rootMargin: "300px" });
    observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [infinite, loading, loadingMore, total, rows.length, offset]);

  function applyFilters() { setOffset(0); load(0, false); }

  async function onBookmark(jobId: number) {
    if (!isSignedIn()) { alert("Sign in to save recruitments."); return; }
    const nowSaved = await toggleBookmark(jobId, saved.has(jobId));
    setSaved(prev => { const next = new Set(prev); nowSaved ? next.add(jobId) : next.delete(jobId); return next; });
  }

  function onShare(job: any) {
    const url = typeof window !== "undefined" ? `${window.location.origin}/jobs/${job.id}` : `/jobs/${job.id}`;
    shareOrCopy(job.title, url, () => { setCopiedId(job.id); setTimeout(() => setCopiedId(null), 2000); });
  }

  return (
    <section>
      <div className="pagehead">
        <div>
          <span className="eyebrow">Government portal</span>
          <h1>{title}</h1>
          {description && <p className="muted">{description}</p>}
        </div>
        <div className="viewtoggle" role="group" aria-label="View mode">
          <button className={view === "cards" ? "active" : ""} onClick={() => setView("cards")} aria-pressed={view === "cards"}>Cards</button>
          <button className={view === "table" ? "active" : ""} onClick={() => setView("table")} aria-pressed={view === "table"}>Table</button>
        </div>
      </div>

      <div className="filters">
        <input className="field" style={{ maxWidth: 240 }} placeholder="Search title, organization…" value={search}
               onChange={e => setSearch(e.target.value)} onKeyDown={e => e.key === "Enter" && applyFilters()} />
        <input className="field" style={{ maxWidth: 200 }} placeholder="Organization" value={organization} onChange={e => setOrganization(e.target.value)} />
        <select className="field" style={{ maxWidth: 160 }} value={govtLevel} onChange={e => setGovtLevel(e.target.value)}>
          <option value="">All levels</option>
          {facets.govt_levels.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
        <select className="field" style={{ maxWidth: 180 }} value={category} onChange={e => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {facets.categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        {showAdvancedFilters && <>
          <input className="field" style={{ maxWidth: 200 }} placeholder="Qualification" value={qualification} onChange={e => setQualification(e.target.value)} />
          <input className="field" style={{ maxWidth: 160 }} placeholder="Location" value={location} onChange={e => setLocation(e.target.value)} />
          <input className="field" style={{ maxWidth: 160 }} placeholder="Advt. number" value={adNumber} onChange={e => setAdNumber(e.target.value)} />
        </>}
        <select className="field" style={{ maxWidth: 170 }} value={sort} onChange={e => setSort(e.target.value)}>
          {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <button className="btn secondary" onClick={applyFilters}>Apply filters</button>
        {allowInfiniteScroll && (
          <label className="checkbox-label">
            <input type="checkbox" checked={infinite} onChange={e => setInfinite(e.target.checked)} /> Infinite scroll
          </label>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <SkeletonCards />}
      {!loading && total !== null && <p className="muted">{total} {total === 1 ? "result" : "results"}</p>}
      {!loading && !rows.length && !error && <div className="empty">No {title.toLowerCase()} match these filters yet — adapter-sourced data appears here as soon as it's ingested and published.</div>}

      {!loading && rows.length > 0 && view === "cards" && (
        <div className="jobs">
          {rows.map((row, i) => {
            const job = row.job; const update = row.update;
            return (
              <article className="card" key={update ? `u${update.id}` : `j${job.id}-${i}`}>
                <div className="row">
                  {job.govt_level && <span className="pill">{job.govt_level}</span>}
                  {job.category && <span className="pill">{job.category}</span>}
                  {job.verified && <span className="verified">Verified</span>}
                </div>
                <h2><a href={`/jobs/${job.id}`}>{update ? update.title : job.title}</a></h2>
                <p className="strong">{job.organization}</p>
                {job.location && <p>{job.location}{job.vacancies ? ` • ${job.vacancies} vacancies` : ""}</p>}
                {job.qualification && <p className="muted">{job.qualification}</p>}
                {job.deadline && <p>Deadline: <b>{job.deadline}</b></p>}
                {update?.event_date && <p>Published: <b>{update.event_date}</b></p>}
                <div className="actions">
                  <a className="btn secondary" href={`/jobs/${job.id}`}>View details</a>
                  {(update?.source_url || job.notification_url) && (
                    <a className="btn secondary" href={safeHref(update?.source_url || job.notification_url)} target="_blank" rel="noreferrer">Notification PDF</a>
                  )}
                  {job.official_url && <a className="btn secondary" href={safeHref(job.official_url)} target="_blank" rel="noreferrer">Official link</a>}
                  <button className="btn secondary" onClick={() => onBookmark(job.id)}>{saved.has(job.id) ? "Saved ✓" : "Save"}</button>
                  <button className="btn secondary" onClick={() => onShare(job)}>{copiedId === job.id ? "Link copied!" : "Share"}</button>
                  {job.apply_url && <a className="btn" href={safeHref(job.apply_url)} target="_blank" rel="noreferrer">Apply now</a>}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {!loading && rows.length > 0 && view === "table" && (
        <table className="govtable">
          <thead><tr><th>Title</th><th>Organization</th><th>Date</th><th>Vacancies</th><th>Actions</th></tr></thead>
          <tbody>
            {rows.map((row, i) => {
              const job = row.job; const update = row.update;
              return (
                <tr key={update ? `u${update.id}` : `j${job.id}-${i}`}>
                  <td><a href={`/jobs/${job.id}`}>{update ? update.title : job.title}</a></td>
                  <td>{job.organization}</td>
                  <td>{update?.event_date || job.deadline || "—"}</td>
                  <td>{job.vacancies ?? "—"}</td>
                  <td>
                    <div className="actions">
                      <button className="btn secondary" onClick={() => onBookmark(job.id)}>{saved.has(job.id) ? "Saved" : "Save"}</button>
                      <button className="btn secondary" onClick={() => onShare(job)}>Share</button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {loadingMore && <p className="muted" style={{ textAlign: "center" }}>Loading more…</p>}
      {infinite && <div ref={sentinelRef} className="sentinel" />}

      {!infinite && total !== null && total > PAGE_SIZE && (
        <div className="actions" style={{ justifyContent: "center", marginTop: 28 }}>
          <button className="btn secondary" disabled={offset === 0} onClick={() => { const n = Math.max(0, offset - PAGE_SIZE); setOffset(n); load(n, false); }}>Previous</button>
          <span className="muted">{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span>
          <button className="btn secondary" disabled={offset + PAGE_SIZE >= total} onClick={() => { const n = offset + PAGE_SIZE; setOffset(n); load(n, false); }}>Next</button>
        </div>
      )}
    </section>
  );
}
