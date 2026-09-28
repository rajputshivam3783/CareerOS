"use client";

// V21.3 — category filter chips (mirrors the .chip/.chip-active
// pattern from the V21.1 discovery filters) plus a small preferences
// panel for the PERSONALIZATION requirement (which opportunity types
// to include, diversity level). Controlled component — the page owns
// state and persistence, same contract as SearchFiltersPanel.

import { ALL_CATEGORIES, CATEGORY_LABELS, RecommendationCategory, RecommendationPreferences } from "@/lib/recommendations";

export function RecommendationCategoryChips({
  active,
  onChange,
}: {
  active: RecommendationCategory | null;
  onChange: (category: RecommendationCategory | null) => void;
}) {
  return (
    <div className="filters">
      <button className={`chip ${active === null ? "chip-active" : ""}`} onClick={() => onChange(null)}>
        All
      </button>
      {ALL_CATEGORIES.map((c) => (
        <button key={c} className={`chip ${active === c ? "chip-active" : ""}`} onClick={() => onChange(c)}>
          {CATEGORY_LABELS[c]}
        </button>
      ))}
    </div>
  );
}

export function RecommendationPreferencesPanel({
  preferences,
  onChange,
}: {
  preferences: RecommendationPreferences;
  onChange: (patch: Partial<RecommendationPreferences>) => void;
}) {
  return (
    <div className="card">
      <h2>Preferences</h2>
      <p className="muted">Choose which opportunity types show up in Jobs For You.</p>
      <div className="grid2">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={preferences.include_private}
            onChange={(e) => onChange({ include_private: e.target.checked })}
          />
          Private jobs
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={preferences.include_government}
            onChange={(e) => onChange({ include_government: e.target.checked })}
          />
          Government recruitment
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={preferences.include_internships}
            onChange={(e) => onChange({ include_internships: e.target.checked })}
          />
          Internships
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={preferences.include_apprenticeships}
            onChange={(e) => onChange({ include_apprenticeships: e.target.checked })}
          />
          Apprenticeships
        </label>
      </div>
      <label className="field-label">
        Variety in results
        <select
          className="field"
          value={preferences.diversity_level}
          onChange={(e) => onChange({ diversity_level: e.target.value as RecommendationPreferences["diversity_level"] })}
        >
          <option value="low">Low — more jobs like my top matches</option>
          <option value="balanced">Balanced</option>
          <option value="high">High — spread across more companies/locations</option>
        </select>
      </label>
    </div>
  );
}
