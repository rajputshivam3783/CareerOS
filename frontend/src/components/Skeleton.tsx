// V19.3 — Government Portal. Reusable loading skeletons so every
// section page shows an obvious loading state instead of a blank
// screen or layout jump while its first fetch resolves.
export function SkeletonCards({ count = 6 }: { count?: number }) {
  return (
    <div className="sectiongrid" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton skeleton-card" />
      ))}
    </div>
  );
}

export function SkeletonLines({ count = 4 }: { count?: number }) {
  return (
    <div aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton skeleton-line" style={{ width: `${90 - i * 10}%` }} />
      ))}
    </div>
  );
}
