// V19.3 — Government Portal. Thin wrapper around the existing V9
// saved-jobs endpoints (app/api/platform.py) — "Save Recruitments /
// Results / Admit Cards" all bookmark the underlying Job row (a
// result/admit-card is a lifecycle event *on* a job, not a separate
// entity), so this reuses SavedJob rather than creating a parallel
// bookmark table per content type.
import { api, token } from "@/lib/api";

export function isSignedIn() {
  return !!token();
}

export async function fetchSavedJobIds(): Promise<Set<number>> {
  if (!isSignedIn()) return new Set();
  try {
    const rows = await api("/saved-jobs?limit=200");
    return new Set(rows.map((j: any) => j.id));
  } catch {
    return new Set();
  }
}

export async function toggleBookmark(jobId: number, currentlySaved: boolean) {
  if (currentlySaved) {
    await api(`/saved-jobs/${jobId}`, { method: "DELETE" });
    return false;
  }
  await api(`/saved-jobs/${jobId}`, { method: "POST" });
  return true;
}
