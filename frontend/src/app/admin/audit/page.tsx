"use client";
/**
 * V25.2 — the platform audit log.
 *
 * Read-only: there is no edit or delete control here because the API
 * exposes none. Records are fetched one page at a time — the whole
 * table is never loaded into the browser.
 */
import { useCallback, useEffect, useState } from "react";
import { AdminShell, AsyncState, Pager } from "@/components/admin/AdminShell";
import { Page, adminApi, formatDate, qs, statusBadgeClass } from "@/lib/adminApi";

type AuditRow = {
  id: number;
  action: string;
  target_type: string;
  target_id: string | null;
  organization_id: number | null;
  actor_label: string | null;
  actor_type: string;
  reason: string | null;
  note: string | null;
  result: string;
  ip_address: string | null;
  request_id: string | null;
  created_at: string;
  metadata: Record<string, unknown> | null;
};

const LIMIT = 25;

export default function AuditPage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [targetType, setTargetType] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [offset, setOffset] = useState(0);
  const [actions, setActions] = useState<string[]>([]);
  const [page, setPage] = useState<Page<AuditRow> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPage(
        await adminApi<Page<AuditRow>>(
          `/audit${qs({
            q: search,
            action,
            target_type: targetType,
            organization_id: organizationId || undefined,
            date_from: dateFrom ? `${dateFrom}T00:00:00` : undefined,
            date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
            limit: LIMIT,
            offset,
          })}`
        )
      );
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [search, action, targetType, organizationId, dateFrom, dateTo, offset]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    adminApi<{ actions: string[] }>("/audit/actions")
      .then((r) => setActions(r.actions))
      .catch(() => undefined);
  }, []);

  return (
    <AdminShell
      title="Audit log"
      description="Every platform administrator action. Append-only — records cannot be edited or removed."
    >
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
          placeholder="Search administrator, action or target"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search audit log"
        />
        <button className="btn" type="submit">
          Search
        </button>
      </form>

      <div className="filters">
        <select
          className="chip"
          value={action}
          onChange={(e) => {
            setOffset(0);
            setAction(e.target.value);
          }}
          aria-label="Filter by action"
        >
          <option value="">All actions</option>
          {actions.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select
          className="chip"
          value={targetType}
          onChange={(e) => {
            setOffset(0);
            setTargetType(e.target.value);
          }}
          aria-label="Filter by target type"
        >
          <option value="">All targets</option>
          <option value="user">User</option>
          <option value="organization">Organization</option>
          <option value="job">Job</option>
          <option value="platform_setting">Platform setting</option>
          <option value="announcement">Announcement</option>
          <option value="bulk">Bulk operation</option>
        </select>
        <input
          className="chip"
          placeholder="Organization ID"
          value={organizationId}
          onChange={(e) => {
            setOffset(0);
            setOrganizationId(e.target.value.replace(/\D/g, ""));
          }}
          aria-label="Filter by organization"
        />
        <label className="field-label">
          From
          <input
            className="field"
            type="date"
            value={dateFrom}
            onChange={(e) => {
              setOffset(0);
              setDateFrom(e.target.value);
            }}
          />
        </label>
        <label className="field-label">
          To
          <input
            className="field"
            type="date"
            value={dateTo}
            onChange={(e) => {
              setOffset(0);
              setDateTo(e.target.value);
            }}
          />
        </label>
      </div>

      <AsyncState
        loading={loading}
        error={error}
        empty={!page || page.results.length === 0}
        emptyMessage="No audit records match these filters."
      >
        {page && (
          <>
            <table className="srctable">
              <caption className="muted">Platform administrator actions</caption>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Action</th>
                  <th scope="col">Target</th>
                  <th scope="col">Administrator</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Result</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {page.results.map((row) => (
                  <tr key={row.id}>
                    <td>{formatDate(row.created_at)}</td>
                    <td>{row.action}</td>
                    <td>
                      {row.target_type}
                      {row.target_id ? ` #${row.target_id}` : ""}
                      {row.organization_id ? ` (org ${row.organization_id})` : ""}
                    </td>
                    <td>
                      {row.actor_label || "—"}
                      <div className="muted">{row.actor_type}</div>
                    </td>
                    <td>{row.reason ? row.reason.replace(/_/g, " ") : "—"}</td>
                    <td>
                      <span className={statusBadgeClass(row.result)}>{row.result}</span>
                    </td>
                    <td>
                      <button
                        className="linkbtn"
                        type="button"
                        onClick={() => setExpanded(expanded === row.id ? null : row.id)}
                      >
                        {expanded === row.id ? "Hide" : "Show"}
                      </button>
                      {expanded === row.id && (
                        <div className="muted">
                          <div>Request: {row.request_id || "—"}</div>
                          <div>IP: {row.ip_address || "—"}</div>
                          {row.note && <div>Note: {row.note}</div>}
                          {row.metadata && <pre className="loglines">{JSON.stringify(row.metadata, null, 2)}</pre>}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager total={page.total} limit={page.limit} offset={page.offset} onChange={setOffset} />
          </>
        )}
      </AsyncState>
    </AdminShell>
  );
}
