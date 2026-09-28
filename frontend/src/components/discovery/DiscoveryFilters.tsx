"use client";
// V21.2 — ADVANCED FILTERS / FILTER UX. Category-aware (different
// fields show for Private/Government/Internship/Apprenticeship, per
// the spec's four distinct filter lists) plus applied-filter chips
// with individual and clear-all removal. Sits alongside — doesn't
// replace — V21.1's SearchFiltersPanel (still used by the plain
// /search page, which spans non-job entity types this component
// intentionally doesn't handle).
//
// Mobile: on narrow viewports this renders behind a "Filters" toggle
// button (a simple show/hide, not a full slide-in drawer animation —
// PERFORMANCE / "Avoid unnecessary animation" was prioritized over a
// more elaborate drawer widget here; see SEARCH_UX.md).

import { useState } from "react";
import { EntityType, SearchFilters } from "@/lib/search";

const WORK_MODES = ["Remote", "Hybrid", "Onsite"];
const EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Contract", "Temporary"];

const FILTER_LABELS: Partial<Record<keyof SearchFilters, string>> = {
  location: "Location",
  organization: "Company",
  category: "Category",
  jobType: "Job Type",
  employmentType: "Employment Type",
  workMode: "Work Mode",
  experience: "Experience",
  education: "Qualification",
  skills: "Skills",
  salaryMin: "Min salary",
  salaryMax: "Max salary",
  postedAfter: "Posted after",
  deadlineBefore: "Deadline before",
};

function AppliedChips({ filters, onClear, onClearAll }: { filters: SearchFilters; onClear: (key: keyof SearchFilters) => void; onClearAll: () => void }) {
  const entries: { key: keyof SearchFilters; label: string }[] = [];
  for (const key of Object.keys(FILTER_LABELS) as (keyof SearchFilters)[]) {
    const value = filters[key];
    if (value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0)) continue;
    const display = Array.isArray(value) ? value.join(", ") : String(value);
    entries.push({ key, label: `${FILTER_LABELS[key]}: ${display}` });
  }
  if (entries.length === 0) return null;
  return (
    <div className="filters" role="group" aria-label="Applied filters">
      {entries.map((e) => (
        <button key={String(e.key)} className="chip chip-active" onClick={() => onClear(e.key)} aria-label={`Remove filter ${e.label}`}>
          {e.label} ✕
        </button>
      ))}
      <button className="chip" onClick={onClearAll}>
        Clear all
      </button>
    </div>
  );
}

export default function DiscoveryFilters({
  category,
  filters,
  onChange,
}: {
  category: EntityType | "ALL";
  filters: SearchFilters;
  onChange: (next: SearchFilters) => void;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);

  function set<K extends keyof SearchFilters>(key: K, value: SearchFilters[K]) {
    onChange({ ...filters, [key]: value || undefined });
  }
  function clearOne(key: keyof SearchFilters) {
    onChange({ ...filters, [key]: undefined });
  }
  function clearAll() {
    onChange({ entityTypes: filters.entityTypes });
  }

  const isPrivate = category === "JOB";
  const isGovernment = category === "GOVERNMENT_RECRUITMENT";
  const isInternship = category === "INTERNSHIP";
  const isApprenticeship = category === "APPRENTICESHIP";
  const isAll = category === "ALL";

  return (
    <div className="search-filters">
      <button
        className="discovery-mobile-toggle btn secondary"
        onClick={() => setMobileOpen((v) => !v)}
        aria-expanded={mobileOpen}
        aria-controls="discovery-filters-body"
      >
        {mobileOpen ? "Hide filters" : "Filters"}
      </button>

      <AppliedChips filters={filters} onClear={clearOne} onClearAll={clearAll} />

      <div id="discovery-filters-body" className={`discovery-filters-body${mobileOpen ? "" : " collapsed"}`}>
      {/* COMMON filters — every category */}
      <div className="filters">
        <input className="field" style={{ maxWidth: 200 }} placeholder="Location" value={filters.location || ""} onChange={(e) => set("location", e.target.value)} aria-label="Location" />
        <input
          className="field"
          style={{ maxWidth: 220 }}
          placeholder="Skills (comma separated)"
          value={(filters.skills || []).join(", ")}
          onChange={(e) => set("skills", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
          aria-label="Skills"
        />
        <input className="field" type="date" style={{ maxWidth: 170 }} title="Posted after" value={filters.postedAfter || ""} onChange={(e) => set("postedAfter", e.target.value)} aria-label="Posted after" />
      </div>

      {/* PRIVATE JOB filters */}
      {(isPrivate || isAll) && (
        <div className="filters">
          <input className="field" style={{ maxWidth: 200 }} placeholder="Company" value={filters.organization || ""} onChange={(e) => set("organization", e.target.value)} aria-label="Company" />
          <input className="field" style={{ maxWidth: 160 }} placeholder="Experience (years)" value={filters.experience || ""} onChange={(e) => set("experience", e.target.value)} aria-label="Experience" />
          <select className="field" style={{ maxWidth: 170 }} value={filters.employmentType || ""} onChange={(e) => set("employmentType", e.target.value)} aria-label="Employment type">
            <option value="">Any employment type</option>
            {EMPLOYMENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <select className="field" style={{ maxWidth: 150 }} value={filters.workMode || ""} onChange={(e) => set("workMode", e.target.value)} aria-label="Work mode">
            <option value="">Any work mode</option>
            {WORK_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <input className="field" style={{ maxWidth: 200 }} placeholder="Department / Industry" value={filters.category || ""} onChange={(e) => set("category", e.target.value)} aria-label="Department or industry" />
          <input className="field" style={{ maxWidth: 200 }} placeholder="Education" value={filters.education || ""} onChange={(e) => set("education", e.target.value)} aria-label="Education" />
          <input className="field" type="number" style={{ maxWidth: 130 }} placeholder="Min salary" value={filters.salaryMin ?? ""} onChange={(e) => set("salaryMin", e.target.value ? Number(e.target.value) : undefined)} aria-label="Minimum salary" />
          <input className="field" type="number" style={{ maxWidth: 130 }} placeholder="Max salary" value={filters.salaryMax ?? ""} onChange={(e) => set("salaryMax", e.target.value ? Number(e.target.value) : undefined)} aria-label="Maximum salary" />
        </div>
      )}

      {/* GOVERNMENT filters — Organization/Qualification/Category/
          Application Deadline are real fields; State/Central/PSU maps
          to Job.govt_level. True reservation-category, per-state, and
          exam-stage tracking have no backing data model yet — not
          shown here rather than faked (see SEARCH_SECURITY_V21_2.md /
          known limitations). */}
      {(isGovernment || isAll) && (
        <div className="filters">
          <input className="field" style={{ maxWidth: 220 }} placeholder="Organization" value={filters.organization || ""} onChange={(e) => set("organization", e.target.value)} aria-label="Government organization" />
          <input className="field" style={{ maxWidth: 200 }} placeholder="Qualification" value={filters.education || ""} onChange={(e) => set("education", e.target.value)} aria-label="Qualification" />
          <input className="field" style={{ maxWidth: 180 }} placeholder="Category" value={filters.category || ""} onChange={(e) => set("category", e.target.value)} aria-label="Category" />
          <input className="field" type="date" style={{ maxWidth: 190 }} title="Application deadline before" value={filters.deadlineBefore || ""} onChange={(e) => set("deadlineBefore", e.target.value)} aria-label="Application deadline before" />
        </div>
      )}

      {/* INTERNSHIP filters */}
      {(isInternship || isAll) && (
        <div className="filters">
          <input className="field" type="number" style={{ maxWidth: 150 }} placeholder="Min stipend" value={filters.salaryMin ?? ""} onChange={(e) => set("salaryMin", e.target.value ? Number(e.target.value) : undefined)} aria-label="Minimum stipend" />
          <input className="field" type="number" style={{ maxWidth: 150 }} placeholder="Max stipend" value={filters.salaryMax ?? ""} onChange={(e) => set("salaryMax", e.target.value ? Number(e.target.value) : undefined)} aria-label="Maximum stipend" />
          <select className="field" style={{ maxWidth: 150 }} value={filters.workMode || ""} onChange={(e) => set("workMode", e.target.value)} aria-label="Remote or on-site">
            <option value="">Remote or on-site</option>
            {WORK_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
      )}

      {/* APPRENTICESHIP filters */}
      {(isApprenticeship || isAll) && (
        <div className="filters">
          <input className="field" style={{ maxWidth: 220 }} placeholder="Organization" value={filters.organization || ""} onChange={(e) => set("organization", e.target.value)} aria-label="Organization" />
          <input className="field" style={{ maxWidth: 180 }} placeholder="Trade" value={filters.category || ""} onChange={(e) => set("category", e.target.value)} aria-label="Trade" />
          <input className="field" style={{ maxWidth: 200 }} placeholder="Qualification" value={filters.education || ""} onChange={(e) => set("education", e.target.value)} aria-label="Qualification" />
        </div>
      )}
      </div>
    </div>
  );
}
