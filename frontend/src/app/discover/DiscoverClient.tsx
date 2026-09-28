"use client";
// V21.2 — Unified Job Discovery. Composes V21.1's search
// infrastructure (runSearch, /search/facets already indexed data) and
// this release's additions (grouped autocomplete, recent searches,
// category-specific filters/cards, salary_asc/desc) into one primary
// discovery experience — per the spec, NOT a rewrite of V21.1's own
// generic /search page, which still exists unchanged for cross-entity
// search (companies/organizations/skills/learning resources).
//
// SEARCH STATE: every filter/sort/page/category/query lives in the
// URL (via useSearchParams + router.replace), so the page survives
// refresh, browser back, and is shareable — e.g.
// /discover?q=python&location=noida&type=JOB&sort=newest&page=2
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { isSignedIn, fetchSavedJobIds, toggleBookmark } from "@/lib/bookmarks";
import {
  EntityType,
  SearchFilters,
  SearchResponse,
  SearchResultItem,
  SortOption,
  runSearch,
} from "@/lib/search";
import { SearchErrorState, SearchLoadingState } from "@/components/search/SearchStates";
import { SearchPagination, SearchSortBar } from "@/components/search/SearchSortBar";
import DiscoveryFilters from "@/components/discovery/DiscoveryFilters";
import DiscoverySearchBox from "@/components/discovery/DiscoverySearchBox";
import { JobResultCard } from "@/components/discovery/JobResultCard";
import RecentSearches from "@/components/discovery/RecentSearches";

type Category = "ALL" | EntityType;

const CATEGORY_TABS: { key: Category; label: string; entityTypes?: EntityType[] }[] = [
  { key: "ALL", label: "All Opportunities", entityTypes: ["JOB", "GOVERNMENT_RECRUITMENT", "INTERNSHIP", "APPRENTICESHIP"] },
  { key: "JOB", label: "Private Jobs" },
  { key: "GOVERNMENT_RECRUITMENT", label: "Government Jobs" },
  { key: "INTERNSHIP", label: "Internships" },
  { key: "APPRENTICESHIP", label: "Apprenticeships" },
];

const JOB_SORT_OPTIONS: SortOption[] = ["relevance", "newest", "oldest", "deadline", "salary_desc", "salary_asc"];

function parseFiltersFromParams(sp: URLSearchParams): SearchFilters {
  const filters: SearchFilters = {};
  if (sp.get("location")) filters.location = sp.get("location")!;
  if (sp.get("organization")) filters.organization = sp.get("organization")!;
  if (sp.get("category")) filters.category = sp.get("category")!;
  if (sp.get("job_type")) filters.jobType = sp.get("job_type")!;
  if (sp.get("employment_type")) filters.employmentType = sp.get("employment_type")!;
  if (sp.get("work_mode")) filters.workMode = sp.get("work_mode")!;
  if (sp.get("experience")) filters.experience = sp.get("experience")!;
  if (sp.get("education")) filters.education = sp.get("education")!;
  const skills = sp.getAll("skills");
  if (skills.length) filters.skills = skills;
  if (sp.get("salary_min")) filters.salaryMin = Number(sp.get("salary_min"));
  if (sp.get("salary_max")) filters.salaryMax = Number(sp.get("salary_max"));
  if (sp.get("posted_after")) filters.postedAfter = sp.get("posted_after")!;
  if (sp.get("deadline_before")) filters.deadlineBefore = sp.get("deadline_before")!;
  return filters;
}

export default function DiscoverClient() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const category = (searchParams.get("type") as Category) || "ALL";
  const query = searchParams.get("q") || "";
  const sort = (searchParams.get("sort") as SortOption) || "relevance";
  const page = Number(searchParams.get("page") || "1");
  const filters = useMemo(() => parseFiltersFromParams(searchParams), [searchParams]);

  const [inputValue, setInputValue] = useState(query);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savedIds, setSavedIds] = useState<Set<number>>(new Set());
  const [recentRefresh, setRecentRefresh] = useState(0);

  useEffect(() => setInputValue(query), [query]);
  useEffect(() => {
    fetchSavedJobIds().then(setSavedIds);
  }, []);

  const pushState = useCallback(
    (next: Partial<{ q: string; type: Category; sort: SortOption; page: number; filters: SearchFilters }>) => {
      const usp = new URLSearchParams(searchParams.toString());
      if (next.q !== undefined) (next.q ? usp.set("q", next.q) : usp.delete("q"));
      if (next.type !== undefined) (next.type !== "ALL" ? usp.set("type", next.type) : usp.delete("type"));
      if (next.sort !== undefined) (next.sort !== "relevance" ? usp.set("sort", next.sort) : usp.delete("sort"));
      if (next.page !== undefined) (next.page > 1 ? usp.set("page", String(next.page)) : usp.delete("page"));
      if (next.filters !== undefined) {
        for (const key of ["location", "organization", "category", "job_type", "employment_type", "work_mode", "experience", "education", "skills", "salary_min", "salary_max", "posted_after", "deadline_before"]) {
          usp.delete(key);
        }
        const f = next.filters;
        if (f.location) usp.set("location", f.location);
        if (f.organization) usp.set("organization", f.organization);
        if (f.category) usp.set("category", f.category);
        if (f.jobType) usp.set("job_type", f.jobType);
        if (f.employmentType) usp.set("employment_type", f.employmentType);
        if (f.workMode) usp.set("work_mode", f.workMode);
        if (f.experience) usp.set("experience", f.experience);
        if (f.education) usp.set("education", f.education);
        for (const s of f.skills || []) usp.append("skills", s);
        if (f.salaryMin != null) usp.set("salary_min", String(f.salaryMin));
        if (f.salaryMax != null) usp.set("salary_max", String(f.salaryMax));
        if (f.postedAfter) usp.set("posted_after", f.postedAfter);
        if (f.deadlineBefore) usp.set("deadline_before", f.deadlineBefore);
      }
      // Any state change other than plain pagination resets to page 1.
      if (next.page === undefined && (next.q !== undefined || next.type !== undefined || next.filters !== undefined || next.sort !== undefined)) {
        usp.delete("page");
      }
      router.replace(`/discover?${usp.toString()}`);
    },
    [router, searchParams]
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const entityTypes = category === "ALL" ? CATEGORY_TABS[0].entityTypes : [category as EntityType];
    runSearch({ q: query, filters: { ...filters, entityTypes }, sort, page, pageSize: 20 })
      .then((r) => {
        if (!cancelled) setResult(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || "Search failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, query, JSON.stringify(filters), sort, page]);

  async function onToggleSave(item: SearchResultItem) {
    const wasSaved = savedIds.has(item.entity_id);
    const next = new Set(savedIds);
    wasSaved ? next.delete(item.entity_id) : next.add(item.entity_id);
    setSavedIds(next);
    try {
      await toggleBookmark(item.entity_id, wasSaved);
    } catch {
      setSavedIds(savedIds); // revert on failure
    }
  }

  function retry() {
    pushState({ q: query });
  }

  const signedIn = isSignedIn();

  return (
    <main id="main" className="page">
      <div className="container">
        <div className="pagehead">
          <div>
            <span className="eyebrow">Discover</span>
            <h1>Find your next opportunity</h1>
            <p className="muted">Private jobs, government recruitments, internships, and apprenticeships — one search.</p>
          </div>
        </div>

        <div className="search" role="search">
          <DiscoverySearchBox
            value={inputValue}
            onChange={setInputValue}
            onSubmit={(v) => {
              pushState({ q: v });
              setRecentRefresh((n) => n + 1);
            }}
          />
          <button className="btn" onClick={() => { pushState({ q: inputValue }); setRecentRefresh((n) => n + 1); }}>
            Search
          </button>
        </div>

        <RecentSearches refreshKey={recentRefresh} />

        <nav className="filters" aria-label="Opportunity category" style={{ marginTop: 18 }}>
          {CATEGORY_TABS.map((tab) => (
            <button
              key={tab.key}
              className={`chip ${category === tab.key ? "chip-active" : ""}`}
              aria-current={category === tab.key}
              onClick={() => pushState({ type: tab.key })}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        <DiscoveryFilters category={category} filters={filters} onChange={(f) => pushState({ filters: f })} />

        <div className="row" style={{ marginTop: 14 }}>
          <span className="muted">{result ? `${result.total_count} result${result.total_count === 1 ? "" : "s"}` : ""}</span>
          <SearchSortBar sort={sort} onChange={(s) => pushState({ sort: s })} options={JOB_SORT_OPTIONS} />
        </div>

        <div className="section">
          {loading && <SearchLoadingState />}
          {!loading && error && <SearchErrorState message={error} onRetry={retry} />}
          {!loading && !error && result && result.items.length === 0 && (
            <div className="empty">
              <p>{query ? <>No results for &ldquo;{query}&rdquo;.</> : <>No results.</>}</p>
              <p className="muted">Try removing a filter, broadening your location, or checking spelling.</p>
              {result.suggestions.length > 0 && (
                <div className="filters" style={{ justifyContent: "center" }}>
                  {result.suggestions.map((s) => (
                    <button key={s.text} className="chip" onClick={() => { setInputValue(s.text); pushState({ q: s.text }); }}>
                      {s.text}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {!loading && !error && result && result.items.length > 0 && (
            <div style={{ display: "grid", gap: 16 }}>
              {result.items.map((item) => (
                <JobResultCard
                  key={`${item.entity_type}-${item.entity_id}`}
                  item={item}
                  saved={savedIds.has(item.entity_id)}
                  onToggleSave={onToggleSave}
                  signedIn={signedIn}
                />
              ))}
            </div>
          )}
          {!loading && !error && result && (
            <SearchPagination page={page} pageSize={result.page_size} totalCount={result.total_count} onChange={(p) => pushState({ page: p })} />
          )}
        </div>
      </div>
    </main>
  );
}
