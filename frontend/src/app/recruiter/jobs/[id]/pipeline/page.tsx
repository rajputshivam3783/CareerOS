"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { api, apiDownload } from "@/lib/api";

// V24.3 — renamed from V18.2's applied/shortlisted/screening/
// interview/technical_round/hr_round/offer/accepted/rejected/
// withdrawn to the canonical hiring-workflow names below (see
// PIPELINE_STAGES's docstring in app.core.constants on the backend).
const STAGES = [
  "new", "reviewing", "shortlisted", "assessment", "interview",
  "offer", "hired", "rejected", "withdrawn",
];

const STAGE_LABEL: Record<string, string> = {
  new: "New",
  reviewing: "Reviewing",
  shortlisted: "Shortlisted",
  assessment: "Assessment",
  interview: "Interview",
  offer: "Offer",
  hired: "Hired",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

type Card = {
  id: number;
  candidate_name: string | null;
  candidate_email: string | null;
  headline: string | null;
  top_skills: string[];
  experience_level: string | null;
  location: string | null;
  pipeline_stage: string;
  days_in_stage: number;
};

export default function Page() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<any>(null);
  const [columns, setColumns] = useState<Record<string, Card[]>>({});
  const [stats, setStats] = useState<any>(null);
  const [staleIds, setStaleIds] = useState<Set<number>>(new Set());
  const [err, setErr] = useState("");
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportingXlsx, setExportingXlsx] = useState(false);
  const [query, setQuery] = useState("");
  const [mobileStage, setMobileStage] = useState("new");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkTarget, setBulkTarget] = useState("reviewing");
  const [bulkBusy, setBulkBusy] = useState(false);

  async function load() {
    try {
      const [j, pipeline, pstats, stale] = await Promise.all([
        api(`/recruiter/jobs/${id}`),
        api(`/recruiter/jobs/${id}/pipeline`),
        api(`/recruiter/jobs/${id}/pipeline/stats`),
        api(`/recruiter/jobs/${id}/pipeline/stale`),
      ]);
      setJob(j);
      setColumns(pipeline.columns);
      setStats(pstats);
      setStaleIds(new Set((stale.stale_candidates || []).map((s: any) => s.applicant_id)));
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  function applyLocalMove(applicantId: number, toStage: string) {
    setColumns((prev) => {
      const next: Record<string, Card[]> = {};
      let card: Card | null = null;
      for (const stage of STAGES) {
        next[stage] = (prev[stage] || []).filter((c) => {
          if (c.id === applicantId) {
            card = { ...c, pipeline_stage: toStage, days_in_stage: 0 };
            return false;
          }
          return true;
        });
      }
      if (card) next[toStage] = [card, ...(next[toStage] || [])];
      return next;
    });
  }

  async function moveCard(applicantId: number, toStage: string) {
    // Optimistic move so the board feels instant even before the
    // network call resolves (spec section 5: rollback + a meaningful
    // error if the backend rejects it).
    applyLocalMove(applicantId, toStage);
    try {
      await api(`/recruiter/applicants/${applicantId}/stage`, {
        method: "PATCH",
        body: JSON.stringify({ pipeline_stage: toStage }),
      });
      setErr("");
    } catch (e: any) {
      setErr(e.message);
      await load(); // roll back to the server's actual state
    }
  }

  async function bulkMove() {
    if (!selected.size) return;
    setBulkBusy(true);
    setErr("");
    try {
      const result = await api(`/recruiter/applicants/bulk-stage`, {
        method: "POST",
        body: JSON.stringify({ applicant_ids: [...selected], pipeline_stage: bulkTarget }),
      });
      if (result.failed > 0) {
        setErr(`${result.succeeded} moved, ${result.failed} failed (they may belong to another job or already be in that stage).`);
      }
      setSelected(new Set());
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBulkBusy(false);
    }
  }

  function toggleSelected(applicantId: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(applicantId)) next.delete(applicantId);
      else next.add(applicantId);
      return next;
    });
  }

  async function exportCsv() {
    setExporting(true);
    setErr("");
    try {
      await apiDownload(`/recruiter/jobs/${id}/applicants/export`, `applicants-job-${id}.csv`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setExporting(false);
    }
  }

  async function exportExcel() {
    setExportingXlsx(true);
    setErr("");
    try {
      await apiDownload(`/recruiter/jobs/${id}/applicants/export.xlsx`, `applicants-job-${id}.xlsx`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setExportingXlsx(false);
    }
  }

  const filteredColumns = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return columns;
    const next: Record<string, Card[]> = {};
    for (const stage of STAGES) {
      next[stage] = (columns[stage] || []).filter((c) => {
        const haystack = [c.candidate_name, c.candidate_email, c.headline, ...(c.top_skills || [])]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      });
    }
    return next;
  }, [columns, query]);

  if (err && !job) return <main className="container page"><p className="error">{err}</p></main>;
  if (!job) return <main className="container page">Loading…</main>;

  return (
    <main className="container page">
      <span className="eyebrow">Candidate pipeline</span>
      <div className="pagehead">
        <div>
          <h1>{job.title}</h1>
          <p className="muted">
            {job.organization} · Drag a candidate card between columns, use each card&apos;s stage menu, or select
            several and use bulk actions below. Click a card to open the full candidate review.
          </p>
        </div>
        <div className="actions">
          <button className="btn secondary" disabled={exporting} onClick={exportCsv}>
            {exporting ? "Exporting…" : "Export CSV"}
          </button>
          <button className="btn secondary" disabled={exportingXlsx} onClick={exportExcel}>
            {exportingXlsx ? "Exporting…" : "Export Excel"}
          </button>
          <a className="btn secondary" href="/recruiter/jobs">
            Back to jobs
          </a>
        </div>
      </div>

      {err && <p className="error" role="alert">{err}</p>}

      {stats && (
        <div className="statgrid" aria-label="Pipeline statistics">
          <div className="statcard"><b>{stats.total_candidates}</b><span>Total candidates</span></div>
          <div className="statcard"><b>{stats.applications_this_week}</b><span>Applications this week</span></div>
          <div className="statcard"><b>{staleIds.size}</b><span>Stale (7+ days inactive)</span></div>
          <div className="statcard"><b>{stats.stage_counts?.hired || 0}</b><span>Hired</span></div>
        </div>
      )}

      <div className="pipeline-toolbar">
        <input
          className="field pipeline-search"
          placeholder="Search by name, skill, or headline"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search candidates in this pipeline"
        />
        {selected.size > 0 && (
          <div className="bulkbar" role="region" aria-label="Bulk actions">
            <span>{selected.size} selected</span>
            <select value={bulkTarget} onChange={(e) => setBulkTarget(e.target.value)} aria-label="Move selected candidates to">
              {STAGES.map((s) => (
                <option key={s} value={s}>{STAGE_LABEL[s]}</option>
              ))}
            </select>
            <button className="btn" disabled={bulkBusy} onClick={bulkMove}>
              {bulkBusy ? "Moving…" : "Move selected"}
            </button>
            <button className="linkbtn" onClick={() => setSelected(new Set())}>Clear</button>
          </div>
        )}
      </div>

      {/* Mobile stage selector (spec section 30/31): the desktop
          multi-column board collapses to one visible column at a time
          on narrow screens, picked from this tab strip, rather than
          relying on horizontal scrolling alone. */}
      <div className="pipeline-mobile-tabs steps" role="tablist" aria-label="Pipeline stage">
        {STAGES.map((stage) => (
          <button
            key={stage}
            type="button"
            role="tab"
            aria-selected={mobileStage === stage}
            className={`step ${mobileStage === stage ? "step-active" : ""}`}
            onClick={() => setMobileStage(stage)}
          >
            {STAGE_LABEL[stage]} ({(filteredColumns[stage] || []).length})
          </button>
        ))}
      </div>

      <div className="board">
        {STAGES.map((stage) => {
          const cards = filteredColumns[stage] || [];
          return (
            <div
              key={stage}
              className={`col ${dragOver === stage ? "dragover" : ""} ${mobileStage === stage ? "mobile-active" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(stage);
              }}
              onDragLeave={() => setDragOver((s) => (s === stage ? null : s))}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(null);
                const applicantId = Number(e.dataTransfer.getData("text/plain"));
                if (applicantId && dragging !== null) moveCard(applicantId, stage);
                setDragging(null);
              }}
            >
              <h3>
                {STAGE_LABEL[stage]} <span>{cards.length}</span>
              </h3>
              {cards.map((c) => {
                const stale = staleIds.has(c.id);
                return (
                  <div key={c.id} className={`kcard ${stale ? "kcard-stale" : ""}`} draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData("text/plain", String(c.id));
                      setDragging(c.id);
                    }}
                    onDragEnd={() => setDragging(null)}
                  >
                    <input
                      type="checkbox"
                      className="kcard-checkbox"
                      checked={selected.has(c.id)}
                      onChange={() => toggleSelected(c.id)}
                      aria-label={`Select ${c.candidate_name || "candidate"}`}
                    />
                    <a href={`/recruiter/jobs/${id}/applicants/${c.id}`} style={{ display: "block", color: "inherit" }}>
                      <b>{c.candidate_name || "Candidate"}</b>
                      <span>{c.candidate_email}</span>
                      {c.headline && <p className="kcard-headline">{c.headline}</p>}
                      {c.top_skills?.length > 0 && (
                        <div className="kcard-skills">
                          {c.top_skills.slice(0, 4).map((s) => (
                            <span key={s} className="kcard-skill">{s}</span>
                          ))}
                        </div>
                      )}
                      <span className={`kcard-days ${stale ? "stale" : ""}`}>
                        {stale ? "⚠ " : ""}
                        {c.days_in_stage === 0 ? "Entered today" : `${c.days_in_stage}d in ${STAGE_LABEL[stage].toLowerCase()}`}
                      </span>
                    </a>
                    <div className="kcard-actions">
                      <a className="linkbtn" href={`/recruiter/jobs/${id}/applicants/${c.id}`}>Add note</a>
                      <a className="linkbtn" href={`/recruiter/jobs/${id}/applicants/${c.id}`}>Schedule interview</a>
                      {stage !== "rejected" && (
                        <button className="linkbtn danger" onClick={() => moveCard(c.id, "rejected")}>Reject</button>
                      )}
                    </div>
                    {/* Non-drag alternative (spec section 5/31): every
                        move drag/drop supports is also reachable from
                        this select, for keyboard and mobile users. */}
                    <label className="sr-only" htmlFor={`stage-select-${c.id}`}>Change stage for {c.candidate_name || "candidate"}</label>
                    <select
                      id={`stage-select-${c.id}`}
                      className="kcard-stage-select"
                      value={stage}
                      onChange={(e) => moveCard(c.id, e.target.value)}
                    >
                      {STAGES.map((s) => (
                        <option key={s} value={s}>{STAGE_LABEL[s]}</option>
                      ))}
                    </select>
                  </div>
                );
              })}
              {!cards.length && <p className="kempty">{query ? "No matches" : "Drop here"}</p>}
            </div>
          );
        })}
      </div>
    </main>
  );
}
