"use client";
/**
 * V25.2 — platform organization management.
 *
 * Suspension is a high-impact action: it unpublishes every live
 * listing the organization owns. The confirmation dialog says so
 * explicitly, and also says what is NOT affected, so the decision is
 * made with the full picture rather than a guess.
 */
import { useCallback, useEffect, useState } from "react";
import { AdminShell, AsyncState, ConfirmDialog, Pager } from "@/components/admin/AdminShell";
import { Page, adminApi, formatDate, qs, statusBadgeClass } from "@/lib/adminApi";

type OrgRow = {
  id: number;
  name: string;
  slug: string | null;
  status: string;
  verification_status: string;
  member_count: number;
  job_count: number;
  application_count: number;
  created_at: string;
};

const LIMIT = 25;

export default function OrganizationsPage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<OrgRow> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<any | null>(null);
  const [pending, setPending] = useState<{ org: OrgRow; action: "suspend" | "reactivate" } | null>(null);
  const [reasons, setReasons] = useState<string[]>(["policy_violation", "suspicious_activity", "other"]);
  const [reason, setReason] = useState("policy_violation");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPage(
        await adminApi<Page<OrgRow>>(`/organizations${qs({ q: search, status, limit: LIMIT, offset })}`)
      );
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [search, status, offset]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    adminApi<{ suspension_reasons: string[] }>("/moderation/reasons")
      .then((r) => setReasons(r.suspension_reasons))
      .catch(() => undefined);
  }, []);

  async function confirmAction() {
    if (!pending) return;
    try {
      const path = `/organizations/${pending.org.id}/${pending.action}`;
      const body =
        pending.action === "suspend"
          ? JSON.stringify({ reason, note: note || null })
          : JSON.stringify({ note: note || null });
      await adminApi(path, { method: "POST", body });
      setPending(null);
      setNote("");
      load();
    } catch (e: any) {
      setError(e.message);
      setPending(null);
    }
  }

  return (
    <AdminShell title="Organizations" description="Search, inspect and manage tenant organizations.">
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
          placeholder="Search organization name"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search organizations"
        />
        <button className="btn" type="submit">
          Search
        </button>
      </form>

      <div className="filters">
        <select
          className="chip"
          value={status}
          onChange={(e) => {
            setOffset(0);
            setStatus(e.target.value);
          }}
          aria-label="Filter by organization status"
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
        emptyMessage="No organizations match these filters."
      >
        {page && (
          <>
            <table className="srctable">
              <caption className="muted">Tenant organizations</caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Status</th>
                  <th scope="col">Verification</th>
                  <th scope="col">Members</th>
                  <th scope="col">Jobs</th>
                  <th scope="col">Applications</th>
                  <th scope="col">Created</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {page.results.map((org) => (
                  <tr key={org.id}>
                    <td>{org.name}</td>
                    <td>
                      <span className={statusBadgeClass(org.status)}>{org.status}</span>
                    </td>
                    <td>{org.verification_status}</td>
                    <td>{org.member_count}</td>
                    <td>{org.job_count}</td>
                    <td>{org.application_count}</td>
                    <td>{formatDate(org.created_at)}</td>
                    <td>
                      <div className="jobcard-actions">
                        <button
                          className="linkbtn"
                          type="button"
                          onClick={async () => {
                            try {
                              setDetail(await adminApi(`/organizations/${org.id}`));
                            } catch (e: any) {
                              setError(e.message);
                            }
                          }}
                        >
                          Details
                        </button>
                        {org.status === "ACTIVE" ? (
                          <button
                            className="linkbtn danger"
                            type="button"
                            onClick={() => setPending({ org, action: "suspend" })}
                          >
                            Suspend
                          </button>
                        ) : (
                          <button
                            className="linkbtn"
                            type="button"
                            onClick={() => setPending({ org, action: "reactivate" })}
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
            <h2>{detail.name}</h2>
            <button className="linkbtn" type="button" onClick={() => setDetail(null)}>
              Close
            </button>
          </div>
          {detail.suspension_reason && <p className="muted">Suspension reason: {detail.suspension_reason}</p>}
          <h3>Members</h3>
          <table className="srctable">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Organization role</th>
                <th scope="col">Membership</th>
                <th scope="col">Platform account</th>
              </tr>
            </thead>
            <tbody>
              {detail.members.map((m: any) => (
                <tr key={m.user_id}>
                  <td>{m.full_name}</td>
                  <td>{m.email}</td>
                  <td>{m.organization_role}</td>
                  <td>{m.membership_status}</td>
                  <td>
                    <span className={statusBadgeClass(m.platform_account_status)}>
                      {m.platform_account_status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <ConfirmDialog
        open={!!pending}
        title={pending?.action === "suspend" ? "Suspend this organization?" : "Reactivate this organization?"}
        body={
          pending?.action === "suspend"
            ? `${pending?.org.name}'s members will lose access to organization resources and every published listing will be unpublished. Applications, history, member accounts and all organization data are preserved.`
            : `${pending?.org.name} will regain access, and the listings unpublished by this suspension will be restored to their previous state.`
        }
        confirmLabel={pending?.action === "suspend" ? "Suspend organization" : "Reactivate organization"}
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
          Internal note (optional — never shown to organization members)
          <input className="field" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
      </ConfirmDialog>
    </AdminShell>
  );
}
