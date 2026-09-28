"use client";
/**
 * V25.2 — platform user management.
 *
 * Shows account-administration facts only. The API deliberately never
 * returns password hashes, OTPs, tokens, resume content or a
 * candidate's private application data, so there is nothing of that
 * kind for this screen to render.
 */
import { useCallback, useEffect, useState } from "react";
import { AdminShell, AsyncState, ConfirmDialog, Pager } from "@/components/admin/AdminShell";
import { Page, adminApi, formatDate, qs, statusBadgeClass } from "@/lib/adminApi";

type UserRow = {
  id: number;
  email: string;
  full_name: string;
  role: string;
  account_status: string;
  active: boolean;
  email_verified: boolean;
  recruiter_status: string | null;
  created_at: string;
  suspended_at: string | null;
};

const LIMIT = 25;

export default function UsersPage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<UserRow> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<any | null>(null);
  const [reasons, setReasons] = useState<string[]>([]);
  const [pending, setPending] = useState<{ user: UserRow; action: "suspend" | "reactivate" } | null>(null);
  const [reason, setReason] = useState("policy_violation");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPage(
        await adminApi<Page<UserRow>>(
          `/users${qs({ q: search, role, account_status: status, limit: LIMIT, offset })}`
        )
      );
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [search, role, status, offset]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    adminApi<{ suspension_reasons: string[] }>("/moderation/reasons")
      .then((r) => setReasons(r.suspension_reasons))
      // A failure here only costs the dropdown its options; the page
      // still works with the default reason.
      .catch(() => setReasons(["policy_violation", "spam", "suspicious_activity", "other"]));
  }, []);

  async function openDetail(userId: number) {
    setDetail(null);
    try {
      setDetail(await adminApi(`/users/${userId}`));
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function confirmAction() {
    if (!pending) return;
    try {
      if (pending.action === "suspend") {
        await adminApi(`/users/${pending.user.id}/suspend`, {
          method: "POST",
          body: JSON.stringify({ reason, note: note || null }),
        });
      } else {
        await adminApi(`/users/${pending.user.id}/reactivate`, {
          method: "POST",
          body: JSON.stringify({ note: note || null }),
        });
      }
      setPending(null);
      setNote("");
      load();
    } catch (e: any) {
      setError(e.message);
      setPending(null);
    }
  }

  return (
    <AdminShell title="Users" description="Search, inspect and manage platform accounts.">
      <form
        className="search"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setSearch(query);
        }}
      >
        <input
          className="field"
          placeholder="Search name or email"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search users"
        />
        <button className="btn" type="submit">
          Search
        </button>
      </form>

      <div className="filters">
        <select
          className="chip"
          value={role}
          onChange={(e) => {
            setOffset(0);
            setRole(e.target.value);
          }}
          aria-label="Filter by role"
        >
          <option value="">All roles</option>
          <option value="candidate">Candidate</option>
          <option value="recruiter">Recruiter</option>
          <option value="admin">Platform admin</option>
          <option value="super_admin">Super admin</option>
        </select>
        <select
          className="chip"
          value={status}
          onChange={(e) => {
            setOffset(0);
            setStatus(e.target.value);
          }}
          aria-label="Filter by account status"
        >
          <option value="">All statuses</option>
          <option value="ACTIVE">Active</option>
          <option value="SUSPENDED">Suspended</option>
          <option value="DEACTIVATED">Deactivated</option>
        </select>
      </div>

      <AsyncState
        loading={loading}
        error={error}
        empty={!page || page.results.length === 0}
        emptyMessage="No users match these filters."
      >
        {page && (
          <>
            <table className="srctable">
              <caption className="muted">Platform user accounts</caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Email</th>
                  <th scope="col">Role</th>
                  <th scope="col">Status</th>
                  <th scope="col">Verified</th>
                  <th scope="col">Joined</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {page.results.map((user) => (
                  <tr key={user.id}>
                    <td>{user.full_name}</td>
                    <td>{user.email}</td>
                    <td>{user.role}</td>
                    <td>
                      <span className={statusBadgeClass(user.account_status)}>{user.account_status}</span>
                    </td>
                    <td>{user.email_verified ? "Yes" : "No"}</td>
                    <td>{formatDate(user.created_at)}</td>
                    <td>
                      <div className="jobcard-actions">
                        <button className="linkbtn" type="button" onClick={() => openDetail(user.id)}>
                          Details
                        </button>
                        {user.account_status === "ACTIVE" ? (
                          <button
                            className="linkbtn danger"
                            type="button"
                            onClick={() => setPending({ user, action: "suspend" })}
                          >
                            Suspend
                          </button>
                        ) : (
                          <button
                            className="linkbtn"
                            type="button"
                            onClick={() => setPending({ user, action: "reactivate" })}
                          >
                            Reactivate
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager total={page.total} limit={page.limit} offset={page.offset} onChange={setOffset} />
          </>
        )}
      </AsyncState>

      {detail && (
        <section className="section card">
          <div className="row">
            <h2>
              {detail.full_name} · {detail.email}
            </h2>
            <button className="linkbtn" type="button" onClick={() => setDetail(null)}>
              Close
            </button>
          </div>
          <p className="muted">
            Platform status <span className={statusBadgeClass(detail.account_status)}>{detail.account_status}</span>
            {detail.suspension_reason ? ` — ${detail.suspension_reason}` : ""}
          </p>
          <h3>Organization memberships</h3>
          <p className="muted">
            An organization role is scoped to that organization only. It confers no platform administration
            capability.
          </p>
          {detail.organization_memberships.length === 0 ? (
            <p className="muted">Not a member of any organization.</p>
          ) : (
            <table className="srctable">
              <thead>
                <tr>
                  <th scope="col">Organization</th>
                  <th scope="col">Organization role</th>
                  <th scope="col">Membership status</th>
                  <th scope="col">Organization status</th>
                </tr>
              </thead>
              <tbody>
                {detail.organization_memberships.map((m: any) => (
                  <tr key={m.organization_id}>
                    <td>{m.organization_name}</td>
                    <td>{m.organization_role}</td>
                    <td>{m.membership_status}</td>
                    <td>{m.organization_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <h3>Activity</h3>
          <div className="statgrid">
            <div className="statcard">
              <b>{detail.activity.applications}</b>
              <span>Applications</span>
            </div>
            <div className="statcard">
              <b>{detail.activity.jobs_owned}</b>
              <span>Jobs owned</span>
            </div>
          </div>
        </section>
      )}

      <ConfirmDialog
        open={!!pending}
        title={pending?.action === "suspend" ? "Suspend this account?" : "Reactivate this account?"}
        body={
          pending?.action === "suspend"
            ? `${pending?.user.email} will be unable to sign in. Their applications, history and organization memberships are preserved.`
            : `${pending?.user.email} will be able to sign in again.`
        }
        confirmLabel={pending?.action === "suspend" ? "Suspend account" : "Reactivate account"}
        reversible
        onConfirm={confirmAction}
        onCancel={() => setPending(null)}
      >
        {pending?.action === "suspend" && (
          <label className="field-label">
            Reason (recorded in the audit trail)
            <select className="field" value={reason} onChange={(e) => setReason(e.target.value)}>
              {reasons.map((r) => (
                <option key={r} value={r}>
                  {r.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="field-label">
          Internal note (optional — never shown to the user)
          <input className="field" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
      </ConfirmDialog>
    </AdminShell>
  );
}
