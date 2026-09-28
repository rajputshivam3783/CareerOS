"use client";
/**
 * V25.2 — the shared chrome for every /admin screen: permission-aware
 * navigation, credential entry, and consistent loading/error/empty
 * states.
 *
 * The navigation is filtered by the permissions the backend reports
 * for the signed-in administrator. That is a usability decision, not a
 * security one — every route behind each link independently enforces
 * its own authorization server-side.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useCallback, useEffect, useState } from "react";
import { PlatformPermissions, adminApi, adminKey, setAdminKey } from "@/lib/adminApi";

const NAV: { href: string; label: string; permission: string }[] = [
  { href: "/admin", label: "Dashboard", permission: "PLATFORM_ANALYTICS" },
  { href: "/admin/users", label: "Users", permission: "USER_MANAGEMENT" },
  { href: "/admin/organizations", label: "Organizations", permission: "ORGANIZATION_MANAGEMENT" },
  { href: "/admin/jobs", label: "Jobs & moderation", permission: "JOB_MODERATION" },
  { href: "/admin/analytics", label: "Analytics", permission: "PLATFORM_ANALYTICS" },
  { href: "/admin/intelligence", label: "Intelligence", permission: "PLATFORM_ANALYTICS" },
  { href: "/admin/data-quality", label: "Data quality", permission: "SYSTEM_CONFIGURATION" },
  { href: "/admin/audit", label: "Audit log", permission: "AUDIT_ACCESS" },
  { href: "/admin/system", label: "System health", permission: "SYSTEM_CONFIGURATION" },
  { href: "/admin/settings", label: "Settings", permission: "SYSTEM_CONFIGURATION" },
];

export function AdminShell({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const [permissions, setPermissions] = useState<PlatformPermissions | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [keyInput, setKeyInput] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPermissions(await adminApi<PlatformPermissions>("/me/platform-permissions"));
    } catch (e: any) {
      setPermissions(null);
      setError(e.message || "Could not verify platform administrator access.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setKeyInput(adminKey() || "");
    load();
  }, [load]);

  function submitKey(event: React.FormEvent) {
    event.preventDefault();
    setAdminKey(keyInput.trim());
    load();
  }

  if (loading) {
    return (
      <main className="container page">
        <p className="loading">Checking platform administrator access…</p>
      </main>
    );
  }

  if (!permissions) {
    return (
      <main className="container narrow">
        <span className="eyebrow">Platform administration</span>
        <h1>Sign in required</h1>
        <p className="muted">
          This area is restricted to platform administrators. Organization owners and admins do not have
          access here — platform administration is a separate authority from organization administration.
        </p>
        <form className="card form" onSubmit={submitKey}>
          <label className="field-label">
            Shared admin key (optional — only if you are not signed in as a platform administrator)
            <input
              className="field"
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="X-Admin-Key"
            />
          </label>
          <div className="actions">
            <button className="btn" type="submit">
              Continue
            </button>
            <Link className="linkbtn" href="/admin-login">
              Sign in as an administrator
            </Link>
          </div>
          {error && <p className="error">{error}</p>}
        </form>
      </main>
    );
  }

  const visible = NAV.filter((item) => permissions.permissions.includes(item.permission));

  return (
    <main className="container page">
      <span className="eyebrow">Platform administration</span>
      <div className="pagehead">
        <div>
          <h1>{title}</h1>
          {description && <p className="muted">{description}</p>}
        </div>
        <p className="muted">
          {permissions.actor_type === "admin_key"
            ? "Authenticated with the shared admin key"
            : `Signed in as ${permissions.role}`}
        </p>
      </div>

      <nav className="filters" aria-label="Platform administration">
        {visible.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`chip${pathname === item.href ? " chip-active" : ""}`}
            aria-current={pathname === item.href ? "page" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      {children}
    </main>
  );
}

/** Consistent async-state rendering, so every screen treats "loading",
 *  "failed" and "there is genuinely nothing here" as three distinct,
 *  visibly different things rather than all showing an empty table. */
export function AsyncState({
  loading,
  error,
  empty,
  emptyMessage,
  children,
}: {
  loading: boolean;
  error: string;
  empty: boolean;
  emptyMessage: string;
  children: ReactNode;
}) {
  if (loading) return <p className="loading">Loading…</p>;
  if (error) return <p className="error">{error}</p>;
  if (empty) return <p className="empty">{emptyMessage}</p>;
  return <>{children}</>;
}

export function Pager({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <div className="pagination">
      <button
        className="linkbtn"
        onClick={() => onChange(Math.max(0, offset - limit))}
        disabled={offset === 0}
        type="button"
      >
        ← Previous
      </button>
      <span>
        Page {page} of {pages} · {total} total
      </span>
      <button
        className="linkbtn"
        onClick={() => onChange(offset + limit)}
        disabled={offset + limit >= total}
        type="button"
      >
        Next →
      </button>
    </div>
  );
}

/**
 * Confirmation prompt for a high-impact action (spec section 26).
 * Destructive-looking actions that are in fact reversible say so, so
 * an administrator isn't deterred from a correct action by an
 * unnecessarily alarming dialog — or lulled into a genuinely
 * irreversible one.
 */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  reversible,
  onConfirm,
  onCancel,
  children,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  reversible?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal-panel card">
        <h2>{title}</h2>
        <p className="muted">{body}</p>
        {reversible && <p className="muted">This is a reversible state change — nothing is deleted.</p>}
        {children}
        <div className="actions">
          <button className="btn" type="button" onClick={onConfirm}>
            {confirmLabel}
          </button>
          <button className="btn secondary" type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
