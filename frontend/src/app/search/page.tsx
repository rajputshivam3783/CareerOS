"use client";

// V21.1 — the unified search page. Composes the reusable components
// in @/components/search rather than containing its own fetch/render
// logic, so another page (e.g. an embedded "related jobs" widget)
// could reuse SearchBox/SearchFiltersPanel/SearchResults directly
// without going through this page.

import { useCallback, useEffect, useState } from "react";
import SearchBox from "@/components/search/SearchBox";
import SearchFiltersPanel from "@/components/search/SearchFiltersPanel";
import SearchResults from "@/components/search/SearchResults";
import { SearchPagination, SearchSortBar } from "@/components/search/SearchSortBar";
import { SearchEmptyState, SearchErrorState, SearchLoadingState } from "@/components/search/SearchStates";
import { runSearch, SearchFilters, SearchResponse, SortOption } from "@/lib/search";

const PAGE_SIZE = 20;

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<SearchFilters>({});
  const [sort, setSort] = useState<SortOption>("relevance");
  const [page, setPage] = useState(1);

  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hasSearched, setHasSearched] = useState(false);

  const load = useCallback(
    async (query: string, currentFilters: SearchFilters, currentSort: SortOption, currentPage: number) => {
      setLoading(true);
      setError("");
      try {
        const result = await runSearch({
          q: query,
          filters: currentFilters,
          sort: currentSort,
          page: currentPage,
          pageSize: PAGE_SIZE,
        });
        setResponse(result);
      } catch (e: any) {
        setError(e.message || "Search failed. Please try again.");
        setResponse(null);
      } finally {
        setLoading(false);
        setHasSearched(true);
      }
    },
    []
  );

  // Filters/sort/page changes re-run the search automatically; typing
  // in the box does not (that's what autocomplete is for) — the box's
  // own onSubmit (Enter key / Search button / picking a suggestion)
  // triggers the query-text search explicitly.
  useEffect(() => {
    load(q, filters, sort, page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, sort, page]);

  function runNewSearch(query: string) {
    setQ(query);
    setPage(1);
    load(query, filters, sort, 1);
  }

  function onFiltersChange(next: SearchFilters) {
    setFilters(next);
    setPage(1);
  }

  function onSortChange(next: SortOption) {
    setSort(next);
    setPage(1);
  }

  return (
    <main className="container page">
      <div className="pagehead">
        <div>
          <span className="eyebrow">Unified search</span>
          <h1>Search CareerOS</h1>
          <p className="muted" style={{ fontSize: 13 }}>
            Jobs, government recruitments, internships, apprenticeships, companies, government organizations, skills
            and learning resources — all in one place.
          </p>
        </div>
        <SearchBox value={q} onChange={setQ} onSubmit={runNewSearch} autoFocus />
      </div>

      <SearchFiltersPanel filters={filters} onChange={onFiltersChange} />

      <div className="row" style={{ marginTop: 10 }}>
        {!loading && response && <p className="muted">{response.total_count} results</p>}
        <SearchSortBar sort={sort} onChange={onSortChange} />
      </div>

      {error && <SearchErrorState message={error} onRetry={() => load(q, filters, sort, page)} />}

      {loading && <SearchLoadingState />}

      {!loading && !error && hasSearched && response && response.items.length === 0 && (
        <SearchEmptyState query={q} suggestions={response.suggestions} onSuggestionClick={runNewSearch} />
      )}

      {!loading && !error && response && response.items.length > 0 && (
        <>
          <SearchResults items={response.items} />
          <SearchPagination page={page} pageSize={PAGE_SIZE} totalCount={response.total_count} onChange={setPage} />
        </>
      )}
    </main>
  );
}
