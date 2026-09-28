"use client";
import { safeHref } from "@/lib/safe";
// V21.2 — JOB RESULT CARDS. Renders a different field set per entity
// type (private job / government / internship / apprenticeship),
// reading everything from the SearchResultItem the V21.1 /search
// endpoint already returns — no second data fetch, no new backend
// call. This sits alongside V21.1's generic SearchResults.tsx (still
// used by the plain /search page for companies/orgs/skills/learning
// resources) rather than replacing it, since a generic card can't
// show job-specific fields like vacancies or an official-source badge
// without either misrepresenting non-job entities or growing
// conditionals V21.1 never needed.
import Link from "next/link";
import { RecentSearchEntry, SearchResultItem, resultHref } from "@/lib/search";

function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function SkillChips({ skills }: { skills: unknown }) {
  if (!Array.isArray(skills) || skills.length === 0) return null;
  return (
    <div style={{ marginTop: 6 }}>
      {skills.slice(0, 6).map((s, i) => (
        <span key={i} className="pill" style={{ marginRight: 6, marginBottom: 4, display: "inline-block", background: "var(--paper)", color: "var(--ink-soft)" }}>
          {String(s)}
        </span>
      ))}
      {skills.length > 6 && <span className="muted"> +{skills.length - 6} more</span>}
    </div>
  );
}

export function JobResultCard({
  item,
  saved,
  onToggleSave,
  signedIn,
}: {
  item: SearchResultItem;
  saved: boolean;
  onToggleSave: (item: SearchResultItem) => void;
  signedIn: boolean;
}) {
  const m = item.metadata || {};
  const isGovernment = item.entity_type === "GOVERNMENT_RECRUITMENT";
  const isInternship = item.entity_type === "INTERNSHIP";
  const isApprenticeship = item.entity_type === "APPRENTICESHIP";
  const officialUrl = (m.official_url as string) || (m.apply_url as string) || null;

  return (
    <article className="card" aria-label={item.title}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 style={{ marginBottom: 2 }}>
            <Link href={resultHref(item)}>{item.title}</Link>
          </h2>
          <p className="muted" style={{ margin: 0 }}>
            {item.organization}
            {item.location ? ` · ${item.location}` : ""}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start", flexShrink: 0 }}>
          {Boolean(m.verified) && <span className="verified">Verified</span>}
          {isGovernment && <span className="pill">Official Source</span>}
        </div>
      </div>

      <div className="filters" style={{ margin: "10px 0 4px" }}>
        {/* PRIVATE JOB fields */}
        {item.entity_type === "JOB" && (
          <>
            {item.category && <span className="chip">{item.category}</span>}
            {m.salary_display ? <span className="chip">{String(m.salary_display)}</span> : null}
            {item.job_type && item.job_type !== "Private" ? null : null}
          </>
        )}

        {/* GOVERNMENT fields */}
        {isGovernment && (
          <>
            {typeof m.vacancies === "number" && <span className="chip">{m.vacancies} vacancies</span>}
            {m.govt_level ? <span className="chip">{String(m.govt_level)}</span> : null}
          </>
        )}

        {/* INTERNSHIP fields */}
        {isInternship && (
          <>
            {m.stipend_display ? <span className="chip">{String(m.stipend_display)} stipend</span> : null}
            {m.duration ? <span className="chip">{String(m.duration)}</span> : null}
          </>
        )}

        {/* APPRENTICESHIP fields */}
        {isApprenticeship && (
          <>
            {item.category ? <span className="chip">{item.category} trade</span> : null}
            {m.duration ? <span className="chip">{String(m.duration)}</span> : null}
          </>
        )}
      </div>

      <p style={{ margin: "4px 0" }}>
        {item.description ? item.description.slice(0, 180) + (item.description.length > 180 ? "…" : "") : null}
      </p>

      <SkillChips skills={m.skills} />

      <div className="filters" style={{ marginTop: 10, fontSize: 13 }}>
        {item.posted_date && <span className="muted">Posted {fmtDate(item.posted_date)}</span>}
        {item.deadline && <span className="muted">Deadline {fmtDate(item.deadline)}</span>}
        {isGovernment && m.ad_number ? <span className="muted">Advt. No. {String(m.ad_number)}</span> : null}
      </div>

      <div className="actions" style={{ marginTop: 12 }}>
        <Link className="btn secondary" href={resultHref(item)}>
          View details
        </Link>
        {isGovernment ? (
          officialUrl ? (
            <a className="btn" href={safeHref(officialUrl)} target="_blank" rel="noreferrer">
              Apply on Official Website
            </a>
          ) : (
            <span className="muted">Official application link not available yet</span>
          )
        ) : m.owner_is_recruiter ? (
          <Link className="btn" href={resultHref(item)}>
            Apply
          </Link>
        ) : officialUrl ? (
          <a className="btn" href={safeHref(officialUrl)} target="_blank" rel="noreferrer">
            Apply on Official Website
          </a>
        ) : null}
        {signedIn && (
          <button className="linkbtn" onClick={() => onToggleSave(item)}>
            {saved ? "★ Saved" : "☆ Save"}
          </button>
        )}
      </div>
    </article>
  );
}
