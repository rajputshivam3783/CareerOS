"use client";

// V21.4 — USER CONTROLS: Personalized Recommendations ON/OFF, a
// non-raw view of what's currently influencing the feed, and the two
// distinct reset actions (stated preferences vs. learned history).
// Controlled visibility, same contract as RecommendationPreferencesPanel.

import { useEffect, useState } from "react";
import {
  PersonalizationSummary,
  clearRecommendationHistory,
  fetchPersonalizationSummary,
  resetRecommendationPreferences,
  setPersonalizationEnabled,
} from "@/lib/recommendations";

const SIGNAL_LABELS: Record<string, string> = {
  skill: "Skills you've engaged with",
  company: "Companies you've engaged with",
  location: "Locations you've engaged with",
  job_type: "Opportunity types you've engaged with",
  role_keyword: "Role types you frequently view",
};

export default function PersonalizationPanel({ onChanged }: { onChanged: () => void }) {
  const [summary, setSummary] = useState<PersonalizationSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetchPersonalizationSummary()
      .then(setSummary)
      .catch(() => {
        /* optional panel — silently unavailable is fine */
      });
  }, []);

  async function toggle(enabled: boolean) {
    setBusy(true);
    try {
      await setPersonalizationEnabled(enabled);
      setSummary((prev) => (prev ? { ...prev, personalization_enabled: enabled } : prev));
      setMessage(enabled ? "Personalization turned on." : "Personalization turned off — recommendations will use only your stated profile and preferences.");
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function handleResetPreferences() {
    setBusy(true);
    try {
      await resetRecommendationPreferences();
      setMessage("Recommendation preferences reset to defaults.");
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function handleClearHistory() {
    setBusy(true);
    try {
      const result = await clearRecommendationHistory();
      setMessage(`Cleared ${result.behavior_signals_cleared} learned signal(s) and ${result.events_cleared} event(s). Jobs you dismissed stay dismissed.`);
      setSummary((prev) => (prev ? { ...prev, top_signals: {} } : prev));
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  if (!summary) return null;

  const hasSignals = Object.keys(summary.top_signals).length > 0;

  return (
    <div className="card">
      <h2>Personalization</h2>
      <p className="muted">
        CareerOS uses your CareerOS activity — jobs you've viewed, saved, applied to, or dismissed — to personalize
        this feed on top of your stated profile and preferences.
      </p>

      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={summary.personalization_enabled}
          disabled={busy}
          onChange={(e) => toggle(e.target.checked)}
        />
        Use my activity to personalize recommendations
      </label>

      {summary.personalization_enabled && (
        <div className="section">
          {hasSignals ? (
            Object.entries(summary.top_signals).map(([type, values]: [string, string[]]) => (
              <p key={type} className="muted">
                <b>{SIGNAL_LABELS[type] ?? type}:</b> {values.join(", ")}
              </p>
            ))
          ) : (
            <p className="muted">No activity-based signal yet — this builds up as you view, save, or apply to jobs.</p>
          )}
        </div>
      )}

      {message && <p className="muted">{message}</p>}

      <div className="actions">
        <button className="btn secondary" disabled={busy} onClick={handleResetPreferences}>
          Reset preferences
        </button>
        <button className="btn secondary" disabled={busy} onClick={handleClearHistory}>
          Clear recommendation history
        </button>
      </div>
    </div>
  );
}
