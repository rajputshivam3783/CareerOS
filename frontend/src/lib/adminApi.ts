/**
 * V25.2 — client for the platform administration API.
 *
 * Authorization note: nothing in this file is a security control. The
 * backend gates every /admin route with its own platform-admin check
 * (see app/core/platform_admin.py); the permission set fetched here is
 * used ONLY to decide which navigation items and buttons to render, so
 * an administrator isn't shown controls that would 403. Editing this
 * file, or the permissions in localStorage, grants nothing.
 */
import { API, formatApiError, token } from "@/lib/api";

const ADMIN_KEY_STORAGE = "careeros_admin_key";

/** The shared break-glass X-Admin-Key, if the operator entered one.
 *  Kept in sessionStorage (cleared when the tab closes) rather than
 *  localStorage, because it is a long-lived shared secret and should
 *  not outlive the session that needed it. */
export function adminKey(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(ADMIN_KEY_STORAGE);
}

export function setAdminKey(value: string) {
  if (typeof window === "undefined") return;
  if (value) sessionStorage.setItem(ADMIN_KEY_STORAGE, value);
  else sessionStorage.removeItem(ADMIN_KEY_STORAGE);
}

export async function adminApi<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const t = token();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  const key = adminKey();
  if (key) headers.set("X-Admin-Key", key);

  const response = await fetch(`${API}/admin${path}`, { ...options, headers });
  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      /* non-JSON error body */
    }
    throw new Error(formatApiError(payload, `Request failed (${response.status})`));
  }
  if (response.status === 204) return null as T;
  return response.json();
}

export type Page<T> = { total: number; limit: number; offset: number; results: T[] };

export type PlatformPermissions = {
  actor_type: string;
  role: string | null;
  permissions: string[];
  can_perform_sensitive_actions: boolean;
};

/** Build a query string, omitting empty values so the backend sees an
 *  absent filter rather than an empty one. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const out = search.toString();
  return out ? `?${out}` : "";
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}

export function statusBadgeClass(status?: string | null): string {
  switch ((status || "").toLowerCase()) {
    case "active":
    case "published":
    case "ok":
    case "success":
    case "sent":
      return "badge badge-active";
    case "suspended":
    case "review":
    case "degraded":
    case "partial":
    case "sending":
      return "badge badge-paused";
    case "rejected":
    case "error":
    case "failure":
    case "deactivated":
      return "badge badge-open";
    default:
      return "badge badge-disabled";
  }
}
