// V21.1 — thin, typed wrapper around GET /search, /search/autocomplete,
// /search/facets. Every search component imports from here rather
// than building query strings itself, so the URL param names only
// live in one place (see backend/app/api/search.py for the source of
// truth this mirrors).

import { API, api, token } from "@/lib/api";

export type EntityType =
  | "JOB"
  | "GOVERNMENT_RECRUITMENT"
  | "INTERNSHIP"
  | "APPRENTICESHIP"
  | "COMPANY"
  | "ORGANIZATION"
  | "SKILL"
  | "LEARNING_RESOURCE";

export type SortOption = "relevance" | "newest" | "oldest" | "deadline" | "salary" | "salary_desc" | "salary_asc";

export interface SearchResultItem {
  entity_type: EntityType;
  entity_id: number;
  title: string;
  description?: string | null;
  organization?: string | null;
  location?: string | null;
  category?: string | null;
  job_type?: string | null;
  posted_date?: string | null;
  deadline?: string | null;
  status: string;
  score: number;
  score_factors: Record<string, number>;
  metadata: Record<string, unknown>;
}

export interface SearchSuggestion {
  kind: "spelling" | "related_term" | "alternative_category";
  text: string;
}

export interface SearchResponse {
  query: string;
  total_count: number;
  page: number;
  page_size: number;
  items: SearchResultItem[];
  facets: Record<string, { value: string; count: number }[]>;
  suggestions: SearchSuggestion[];
}

export interface SearchFilters {
  entityTypes?: EntityType[];
  location?: string;
  organization?: string;
  category?: string;
  jobType?: string;
  employmentType?: string;
  workMode?: string;
  experience?: string;
  education?: string;
  skills?: string[];
  salaryMin?: number;
  salaryMax?: number;
  postedAfter?: string; // YYYY-MM-DD
  deadlineBefore?: string; // YYYY-MM-DD
}

export interface SearchParams {
  q: string;
  filters?: SearchFilters;
  sort?: SortOption;
  page?: number;
  pageSize?: number;
}

function filtersToParams(params: URLSearchParams, filters?: SearchFilters) {
  if (!filters) return;
  for (const et of filters.entityTypes || []) params.append("entity_type", et);
  for (const s of filters.skills || []) params.append("skills", s);
  if (filters.location) params.set("location", filters.location);
  if (filters.organization) params.set("organization", filters.organization);
  if (filters.category) params.set("category", filters.category);
  if (filters.jobType) params.set("job_type", filters.jobType);
  if (filters.employmentType) params.set("employment_type", filters.employmentType);
  if (filters.workMode) params.set("work_mode", filters.workMode);
  if (filters.experience) params.set("experience", filters.experience);
  if (filters.education) params.set("education", filters.education);
  if (filters.salaryMin != null) params.set("salary_min", String(filters.salaryMin));
  if (filters.salaryMax != null) params.set("salary_max", String(filters.salaryMax));
  if (filters.postedAfter) params.set("posted_after", filters.postedAfter);
  if (filters.deadlineBefore) params.set("deadline_before", filters.deadlineBefore);
}

/** GET /search. Works signed-out; automatically includes the bearer
 * token when present so a logged-in recruiter/admin sees their own
 * unpublished postings alongside public results (see
 * SEARCH_PERMISSIONS.md) — plain `fetch`, not the `api()` helper from
 * `@/lib/api`, since this endpoint must not redirect/clear the
 * session on a 401 the way authenticated-only endpoints do. */
export async function runSearch(params: SearchParams): Promise<SearchResponse> {
  const usp = new URLSearchParams();
  usp.set("q", params.q ?? "");
  usp.set("sort", params.sort ?? "relevance");
  usp.set("page", String(params.page ?? 1));
  usp.set("page_size", String(params.pageSize ?? 20));
  filtersToParams(usp, params.filters);

  const headers: HeadersInit = {};
  const t = token();
  if (t) headers["Authorization"] = `Bearer ${t}`;

  const r = await fetch(`${API}/search?${usp.toString()}`, { headers });
  if (!r.ok) throw new Error(`Search failed (${r.status})`);
  return r.json();
}

/** GET /search/autocomplete. Callers should debounce keystrokes
 * themselves (see useDebouncedValue in SearchBox.tsx) — this function
 * fires one request per call, no built-in debounce, so it stays
 * reusable outside a typing context (e.g. a "did you mean" retry). */
export async function fetchAutocomplete(q: string, entityTypes?: EntityType[], limit = 10): Promise<string[]> {
  if (!q.trim()) return [];
  const usp = new URLSearchParams();
  usp.set("q", q);
  usp.set("limit", String(limit));
  for (const et of entityTypes || []) usp.append("entity_type", et);
  const r = await fetch(`${API}/search/autocomplete?${usp.toString()}`);
  if (!r.ok) return [];
  const body = await r.json();
  return body.suggestions ?? [];
}

/** GET /search/autocomplete/grouped (V21.2) — same debounce contract
 * as fetchAutocomplete: caller debounces, this fires once per call. */
export async function fetchGroupedAutocomplete(q: string, limitPerGroup = 6): Promise<Record<string, string[]>> {
  if (!q.trim()) return {};
  const usp = new URLSearchParams();
  usp.set("q", q);
  usp.set("limit_per_group", String(limitPerGroup));
  const r = await fetch(`${API}/search/autocomplete/grouped?${usp.toString()}`);
  if (!r.ok) return {};
  const body = await r.json();
  return body.groups ?? {};
}

export const AUTOCOMPLETE_GROUP_LABELS: Record<string, string> = {
  job_titles: "Job Titles",
  companies: "Companies",
  organizations: "Government Organizations",
  skills: "Skills",
  locations: "Locations",
};

/** GET /search/facets. */
export async function fetchFacets(
  facetFields: string[],
  entityTypes?: EntityType[]
): Promise<Record<string, { value: string; count: number }[]>> {
  const usp = new URLSearchParams();
  for (const f of facetFields) usp.append("facet", f);
  for (const et of entityTypes || []) usp.append("entity_type", et);
  const r = await fetch(`${API}/search/facets?${usp.toString()}`);
  if (!r.ok) return {};
  return r.json();
}

export const ENTITY_TYPE_LABELS: Record<EntityType, string> = {
  JOB: "Jobs",
  GOVERNMENT_RECRUITMENT: "Government Recruitments",
  INTERNSHIP: "Internships",
  APPRENTICESHIP: "Apprenticeships",
  COMPANY: "Companies",
  ORGANIZATION: "Government Organizations",
  SKILL: "Skills",
  LEARNING_RESOURCE: "Learning Resources",
};

/** Where a result's "View" link should point. Falls back to the
 * unified search page itself (with the item pre-selected via query
 * param) for entity types that don't have their own detail page yet. */
export function resultHref(item: SearchResultItem): string {
  switch (item.entity_type) {
    case "JOB":
    case "GOVERNMENT_RECRUITMENT":
    case "INTERNSHIP":
    case "APPRENTICESHIP":
      return `/jobs/${item.entity_id}`;
    case "COMPANY": {
      const slug = item.metadata?.slug;
      return typeof slug === "string" && slug ? `/companies/${slug}` : "/companies";
    }
    case "ORGANIZATION":
      return "/government";
    case "LEARNING_RESOURCE":
      return "/learning";
    case "SKILL":
      return "/learning";
    default:
      return "#";
  }
}

// ---------------------------------------------------------------------------
// V21.2 — Recent Searches. Candidate-only (requires a bearer token);
// every function below relies on `api()` from @/lib/api rather than
// plain fetch, since these ARE meant to redirect/clear session on 401
// like any other authenticated-only endpoint.
// ---------------------------------------------------------------------------

export interface RecentSearchEntry {
  id: number;
  query: string;
  entity_types: EntityType[];
  filters: Record<string, unknown>;
  result_count: number;
  created_at: string;
}

export async function fetchRecentSearches(): Promise<RecentSearchEntry[]> {
  try {
    return await api("/search/recent");
  } catch {
    return [];
  }
}

export async function deleteRecentSearch(id: number): Promise<void> {
  await api(`/search/recent/${id}`, { method: "DELETE" });
}

export async function clearRecentSearches(): Promise<void> {
  await api("/search/recent", { method: "DELETE" });
}

/** Rebuild a shareable /discover URL from a stored recent search —
 * this is the "Reuse" action in RECENT SEARCHES. */
export function recentSearchHref(entry: RecentSearchEntry): string {
  const usp = new URLSearchParams();
  if (entry.query) usp.set("q", entry.query);
  if (entry.entity_types.length === 1) usp.set("type", entry.entity_types[0]);
  const f = entry.filters || {};
  for (const [key, value] of Object.entries(f)) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      for (const v of value) usp.append(key, String(v));
    } else {
      usp.set(key, String(value));
    }
  }
  return `/discover?${usp.toString()}`;
}
