"use client";

// V21.1 — reusable Sort + Pagination bar. Controlled component, same
// pattern as SearchFiltersPanel: caller owns the state.

import { SortOption } from "@/lib/search";

const SORT_LABELS: Record<SortOption, string> = {
  relevance: "Relevance",
  newest: "Newest",
  oldest: "Oldest",
  deadline: "Deadline",
  salary: "Salary",
  salary_desc: "Salary: High to Low",
  salary_asc: "Salary: Low to High",
};

// V21.1's plain /search page covers companies/organizations/skills
// too, where "High to Low"/"Low to High" phrasing doesn't apply —
// it keeps showing the original five options. The V21.2 discovery
// page (job-family entities only) shows the two directional options
// instead of the ambiguous bare "salary" — see DiscoverySortBar.
const DEFAULT_VISIBLE: SortOption[] = ["relevance", "newest", "oldest", "deadline", "salary"];

export function SearchSortBar({
  sort,
  onChange,
  options = DEFAULT_VISIBLE,
}: {
  sort: SortOption;
  onChange: (sort: SortOption) => void;
  options?: SortOption[];
}) {
  return (
    <select className="field" style={{ maxWidth: 180 }} value={sort} onChange={(e) => onChange(e.target.value as SortOption)}>
      {options.map((s) => (
        <option key={s} value={s}>
          Sort: {SORT_LABELS[s]}
        </option>
      ))}
    </select>
  );
}

export function SearchPagination({
  page,
  pageSize,
  totalCount,
  onChange,
}: {
  page: number;
  pageSize: number;
  totalCount: number;
  onChange: (page: number) => void;
}) {
  if (totalCount <= pageSize) return null;
  const lastPage = Math.ceil(totalCount / pageSize);
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalCount);
  return (
    <div className="actions" style={{ justifyContent: "center", marginTop: 28 }}>
      <button className="btn secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        Previous
      </button>
      <span className="muted">
        {start}–{end} of {totalCount}
      </span>
      <button className="btn secondary" disabled={page >= lastPage} onClick={() => onChange(page + 1)}>
        Next
      </button>
    </div>
  );
}
