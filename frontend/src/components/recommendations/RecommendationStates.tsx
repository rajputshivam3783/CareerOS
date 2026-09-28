// V21.3 — reusable Loading/Empty/Cold-start/Error states, same
// contract as SearchStates.tsx (V21.1).

import { SkeletonCards } from "@/components/Skeleton";

export function RecommendationsLoadingState() {
  return <SkeletonCards count={6} />;
}

export function RecommendationsErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="empty">
      <p className="error">{message}</p>
      <button className="btn secondary" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

export function RecommendationsEmptyState({ hasFilters, onClearFilters }: { hasFilters: boolean; onClearFilters: () => void }) {
  return (
    <div className="empty">
      {hasFilters ? (
        <>
          <p>No jobs match this filter right now.</p>
          <button className="btn secondary" onClick={onClearFilters}>
            Clear filter
          </button>
        </>
      ) : (
        <p>
          No recommendations yet. Add skills and a career goal on your <a href="/dashboard">dashboard</a>, or upload a
          resume, so Jobs For You has something real to match against.
        </p>
      )}
    </div>
  );
}

/** COLD START — shown alongside results (not instead of them) when the
 * candidate has little/no profile data yet, so the list is honestly
 * labelled as broad/recent rather than personalized. Never claims
 * personalization it can't back up. */
export function ColdStartNotice() {
  return (
    <div className="empty" style={{ padding: "16px 24px", textAlign: "left" }}>
      <p className="muted">
        These are recent and popular opportunities — add skills, a resume, or a career goal on your{" "}
        <a href="/dashboard">dashboard</a> to get recommendations matched to you.
      </p>
    </div>
  );
}
