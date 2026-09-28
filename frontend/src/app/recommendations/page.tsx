"use client";

// V21.3 — "Jobs For You". Composes the reusable components in
// @/components/recommendations rather than containing its own
// fetch/render logic, same convention as the V21.1 search page.

import { useCallback, useEffect, useState } from "react";
import PersonalizationPanel from "@/components/recommendations/PersonalizationPanel";
import RecommendationCard from "@/components/recommendations/RecommendationCard";
import { RecommendationCategoryChips, RecommendationPreferencesPanel } from "@/components/recommendations/RecommendationFilters";
import {
  ColdStartNotice,
  RecommendationsEmptyState,
  RecommendationsErrorState,
  RecommendationsLoadingState,
} from "@/components/recommendations/RecommendationStates";
import {
  RecommendationCategory,
  RecommendationPreferences,
  RecommendationsResponse,
  fetchRecommendationPreferences,
  fetchRecommendations,
  logGenericEvent,
  updateRecommendationPreferences,
} from "@/lib/recommendations";
import { isSignedIn } from "@/lib/bookmarks";

export default function RecommendationsPage() {
  const [response, setResponse] = useState<RecommendationsResponse | null>(null);
  const [category, setCategory] = useState<RecommendationCategory | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [showPreferences, setShowPreferences] = useState(false);
  const [showPersonalization, setShowPersonalization] = useState(false);
  const [preferences, setPreferences] = useState<RecommendationPreferences | null>(null);

  const load = useCallback(async (cat: RecommendationCategory | null, forceRefresh = false) => {
    forceRefresh ? setRefreshing(true) : setLoading(true);
    setError("");
    try {
      const result = await fetchRecommendations({ category: cat ?? undefined, refresh: forceRefresh });
      setResponse(result);
    } catch (e: any) {
      setError(e.message || "Couldn't load recommendations. Please try again.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!isSignedIn()) {
      location.href = "/login";
      return;
    }
    load(category);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category]);

  function onCategoryChange(next: RecommendationCategory | null) {
    setCategory(next);
    // V21.4 — BEHAVIORAL SIGNALS: Filter Usage.
    logGenericEvent("filter_usage", { dimension: "category", value: next ?? "all" });
  }

  function onDismissed(jobId: number) {
    setResponse((prev) => (prev ? { ...prev, items: prev.items.filter((i) => i.job_id !== jobId) } : prev));
  }

  async function openPreferences() {
    setShowPreferences((v) => !v);
    if (!preferences) {
      try {
        setPreferences(await fetchRecommendationPreferences());
      } catch {
        /* preferences are optional to load; the toggle just won't render */
      }
    }
  }

  async function onPreferencesChange(patch: Partial<RecommendationPreferences>) {
    if (!preferences) return;
    const next = { ...preferences, ...patch };
    setPreferences(next);
    try {
      await updateRecommendationPreferences(patch);
      load(category, true);
    } catch {
      /* revert not attempted — next load() will reconcile from the server */
    }
  }

  return (
    <main className="container page">
      <div className="pagehead">
        <div>
          <span className="eyebrow">Jobs for you</span>
          <h1>Recommended for you</h1>
        </div>
        <div className="actions">
          <button className="btn secondary" onClick={() => setShowPersonalization((v) => !v)}>
            Personalization
          </button>
          <button className="btn secondary" onClick={openPreferences}>
            Preferences
          </button>
          <button className="btn secondary" disabled={refreshing} onClick={() => load(category, true)}>
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {showPersonalization && <PersonalizationPanel onChanged={() => load(category, true)} />}

      {showPreferences && preferences && (
        <RecommendationPreferencesPanel preferences={preferences} onChange={onPreferencesChange} />
      )}

      <RecommendationCategoryChips active={category} onChange={onCategoryChange} />

      {loading ? (
        <RecommendationsLoadingState />
      ) : error ? (
        <RecommendationsErrorState message={error} onRetry={() => load(category)} />
      ) : !response || response.items.length === 0 ? (
        <RecommendationsEmptyState hasFilters={category !== null} onClearFilters={() => setCategory(null)} />
      ) : (
        <>
          {response.is_cold_start && <ColdStartNotice />}
          <div className="jobs">
            {response.items.map((item) => (
              <RecommendationCard key={item.job_id} item={item} onDismissed={onDismissed} />
            ))}
          </div>
        </>
      )}
    </main>
  );
}
