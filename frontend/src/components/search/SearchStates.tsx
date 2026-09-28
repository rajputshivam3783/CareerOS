// V21.1 — reusable Empty/Loading/Error states, matching the spec's
// FRONTEND section. Loading reuses the existing SkeletonCards
// component (V19.3, app/components/Skeleton.tsx) rather than a new
// spinner, so a search results page loads the same way every other
// section page in the app already does.

import { SkeletonCards } from "@/components/Skeleton";
import { SearchSuggestion } from "@/lib/search";

export function SearchLoadingState() {
  return <SkeletonCards count={6} />;
}

export function SearchErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="empty">
      <p className="error">{message}</p>
      <button className="btn secondary" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

export function SearchEmptyState({
  query,
  suggestions,
  onSuggestionClick,
}: {
  query: string;
  suggestions: SearchSuggestion[];
  onSuggestionClick: (text: string) => void;
}) {
  const spelling = suggestions.filter((s) => s.kind === "spelling");
  const alternatives = suggestions.filter((s) => s.kind === "alternative_category" || s.kind === "related_term");

  return (
    <div className="empty">
      <p>
        {query ? (
          <>No results for &ldquo;{query}&rdquo;.</>
        ) : (
          <>No results.</>
        )}
      </p>
      {spelling.length > 0 && (
        <p className="muted">
          Did you mean{" "}
          {spelling.map((s, i) => (
            <span key={s.text}>
              <button className="linkbtn" onClick={() => onSuggestionClick(s.text)}>
                {s.text}
              </button>
              {i < spelling.length - 1 ? ", " : ""}
            </span>
          ))}
          ?
        </p>
      )}
      {alternatives.length > 0 && (
        <div className="filters" style={{ justifyContent: "center" }}>
          {alternatives.map((s) => (
            <button key={s.text} className="chip" onClick={() => onSuggestionClick(s.text)}>
              {s.text}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
