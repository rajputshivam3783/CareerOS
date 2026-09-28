"use client";

// V21.1 — reusable Filters panel. Purely controlled: the caller owns
// the SearchFilters state and passes it down along with a setter, so
// this component has no fetch/state logic of its own beyond the
// entity-type chips (which double as the ENTITY TYPES selector) —
// matches the FILTER INFRASTRUCTURE / ENTITY TYPES sections of
// SEARCH_ARCHITECTURE.md.

import { ENTITY_TYPE_LABELS, EntityType, SearchFilters } from "@/lib/search";

const ALL_ENTITY_TYPES = Object.keys(ENTITY_TYPE_LABELS) as EntityType[];

const WORK_MODES = ["Remote", "Hybrid", "Onsite"];

export default function SearchFiltersPanel({
  filters,
  onChange,
  showEntityTypes = true,
}: {
  filters: SearchFilters;
  onChange: (next: SearchFilters) => void;
  /** Hide the entity-type chips when the caller already scopes the
   * page to one entity type (e.g. a jobs-only search embed). */
  showEntityTypes?: boolean;
}) {
  function toggleEntityType(et: EntityType) {
    const current = filters.entityTypes || [];
    const next = current.includes(et) ? current.filter((x) => x !== et) : [...current, et];
    onChange({ ...filters, entityTypes: next });
  }

  function set<K extends keyof SearchFilters>(key: K, value: SearchFilters[K]) {
    onChange({ ...filters, [key]: value || undefined });
  }

  return (
    <div className="search-filters">
      {showEntityTypes && (
        <div className="filters">
          {ALL_ENTITY_TYPES.map((et) => (
            <button
              key={et}
              className={`chip ${filters.entityTypes?.includes(et) ? "chip-active" : ""}`}
              onClick={() => toggleEntityType(et)}
            >
              {ENTITY_TYPE_LABELS[et]}
            </button>
          ))}
        </div>
      )}

      <div className="filters">
        <input
          className="field"
          style={{ maxWidth: 220 }}
          placeholder="Location"
          value={filters.location || ""}
          onChange={(e) => set("location", e.target.value)}
        />
        <input
          className="field"
          style={{ maxWidth: 220 }}
          placeholder="Organization"
          value={filters.organization || ""}
          onChange={(e) => set("organization", e.target.value)}
        />
        <select
          className="field"
          style={{ maxWidth: 180 }}
          value={filters.workMode || ""}
          onChange={(e) => set("workMode", e.target.value)}
        >
          <option value="">Any work mode</option>
          {WORK_MODES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <input
          className="field"
          style={{ maxWidth: 160 }}
          placeholder="Experience"
          value={filters.experience || ""}
          onChange={(e) => set("experience", e.target.value)}
        />
      </div>

      <div className="filters">
        <input
          className="field"
          type="number"
          style={{ maxWidth: 150 }}
          placeholder="Min salary"
          value={filters.salaryMin ?? ""}
          onChange={(e) => set("salaryMin", e.target.value ? Number(e.target.value) : undefined)}
        />
        <input
          className="field"
          type="number"
          style={{ maxWidth: 150 }}
          placeholder="Max salary"
          value={filters.salaryMax ?? ""}
          onChange={(e) => set("salaryMax", e.target.value ? Number(e.target.value) : undefined)}
        />
        <input
          className="field"
          type="date"
          style={{ maxWidth: 170 }}
          title="Posted after"
          value={filters.postedAfter || ""}
          onChange={(e) => set("postedAfter", e.target.value)}
        />
        <input
          className="field"
          type="date"
          style={{ maxWidth: 170 }}
          title="Deadline before"
          value={filters.deadlineBefore || ""}
          onChange={(e) => set("deadlineBefore", e.target.value)}
        />
        {(filters.location ||
          filters.organization ||
          filters.workMode ||
          filters.experience ||
          filters.salaryMin ||
          filters.salaryMax ||
          filters.postedAfter ||
          filters.deadlineBefore ||
          (filters.entityTypes && filters.entityTypes.length > 0)) && (
          <button className="chip" onClick={() => onChange({})}>
            Clear filters
          </button>
        )}
      </div>
    </div>
  );
}
