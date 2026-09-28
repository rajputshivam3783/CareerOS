"use client";
// V21.2 — RECENT SEARCHES panel. Candidate-only (isSignedIn gate),
// reuses GET/DELETE /search/recent added this release. View/Reuse/
// Delete/Clear per the spec.
import { useEffect, useState } from "react";
import Link from "next/link";
import { isSignedIn } from "@/lib/bookmarks";
import { RecentSearchEntry, clearRecentSearches, deleteRecentSearch, fetchRecentSearches, recentSearchHref } from "@/lib/search";

export default function RecentSearches({ refreshKey }: { refreshKey?: number }) {
  const [entries, setEntries] = useState<RecentSearchEntry[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!isSignedIn()) {
      setLoaded(true);
      return;
    }
    fetchRecentSearches().then((rows) => {
      setEntries(rows);
      setLoaded(true);
    });
  }, [refreshKey]);

  if (!isSignedIn() || !loaded || entries.length === 0) return null;

  async function remove(id: number) {
    setEntries((prev) => prev.filter((e) => e.id !== id));
    try {
      await deleteRecentSearch(id);
    } catch {
      // best-effort UI update; a failed delete just means it may
      // reappear next load, which is safe (never silently loses data
      // the user didn't ask to keep)
    }
  }

  async function clearAll() {
    const previous = entries;
    setEntries([]);
    try {
      await clearRecentSearches();
    } catch {
      setEntries(previous);
    }
  }

  return (
    <div className="section" aria-label="Recent searches">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="muted" style={{ fontWeight: 700, fontSize: 13 }}>
          Recent searches
        </span>
        <button className="linkbtn" onClick={clearAll}>
          Clear history
        </button>
      </div>
      <div className="filters">
        {entries.map((entry) => (
          <span key={entry.id} className="chip" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <Link href={recentSearchHref(entry)} style={{ color: "inherit" }}>
              {entry.query || "(filters only)"}
            </Link>
            <button
              type="button"
              className="linkbtn"
              style={{ padding: 0, fontSize: 12 }}
              aria-label={`Remove recent search: ${entry.query}`}
              onClick={() => remove(entry.id)}
            >
              ✕
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}
