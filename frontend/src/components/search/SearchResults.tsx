// V21.1 — reusable Results list. Renders any SearchResultItem
// generically (entity-type badge, title, org/location, score-factor
// tooltip) rather than needing a separate results component per
// entity type — a facet-scoped or unscoped search both render through
// this one component.

import { ENTITY_TYPE_LABELS, SearchResultItem, resultHref } from "@/lib/search";

function ScoreBadge({ item }: { item: SearchResultItem }) {
  const topFactors = Object.entries(item.score_factors)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([k]) => k.replace(/_/g, " "))
    .join(", ");
  if (!topFactors) return null;
  return (
    <span className="pill" title={`Matched on: ${topFactors}`}>
      Why this result
    </span>
  );
}

export default function SearchResults({ items }: { items: SearchResultItem[] }) {
  return (
    <div className="jobs search-results">
      {items.map((item) => (
        <article className="card" key={`${item.entity_type}-${item.entity_id}`}>
          <div className="row">
            <span className="pill">{ENTITY_TYPE_LABELS[item.entity_type]}</span>
            {item.job_type && item.job_type !== item.entity_type && <span className="pill">{item.job_type}</span>}
            <ScoreBadge item={item} />
          </div>
          <h2>
            <a href={resultHref(item)}>{item.title}</a>
          </h2>
          {item.organization && <p className="strong">{item.organization}</p>}
          {item.location && <p>{item.location}</p>}
          {item.description && (
            <p className="muted" style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
              {item.description}
            </p>
          )}
          {item.deadline && (
            <p>
              Deadline: <b>{item.deadline}</b>
            </p>
          )}
          <div className="actions">
            <a className="btn secondary" href={resultHref(item)}>
              View details
            </a>
          </div>
        </article>
      ))}
    </div>
  );
}
