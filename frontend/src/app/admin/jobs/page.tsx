"use client";
/**
 * V25.2 — platform job moderation.
 *
 * Also carries the pending-recruiter approvals that lived on /admin
 * before this version, so every moderation decision an administrator
 * makes is in one place.
 *
 * All four job actions are reversible status transitions. There is no
 * delete control here, and the API exposes no bulk deletion at all.
 */
import { useCallback, useEffect, useState } from "react";
import { AdminShell, AsyncState, ConfirmDialog, Pager } from "@/components/admin/AdminShell";
import { Page, adminApi, formatDate, qs, statusBadgeClass } from "@/lib/adminApi";

type JobRow = {
  id: number;
  title: string;
  organization: string;
  status: string;
  owner_user_id: number | null;
  created_at: string;
  published_at: string | null;
  moderation_reason: string | null;
  moderation_note: string | null;
};

type Action = "approve" | "reject" | "suspend" | "restore";
const NEEDS_REASON: Action[] = ["reject", "suspend"];
const LIMIT = 25;

export default function JobsPage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("review");
  const [createdFrom, setCreatedFrom] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<JobRow> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [statuses, setStatuses] = useState<string[]>([]);
  const [reasons, setReasons] = useState<string[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [pending, setPending] = useState<{ action: Action; jobIds: number[] } | null>(null);
  const [reason, setReason] = useState("policy_violation");
  const [note, setNote] = useState("");
  const [recruiters, setRecruiters] = useState<any[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPage(
        await adminApi<Page<JobRow>>(
          `/jobs${qs({ q: search, status, created_from: createdFrom || undefined, limit: LIMIT, offset })}`
        )
      );
      setSelected([]);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [search, status, createdFrom, offset]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    adminApi<{ job_moderation_reasons: string[]; job_statuses: string[] }>("/moderation/reasons")
      .then((r) => {
        setReasons(r.job_moderation_reasons);
        setStatuses(r.job_statuses);
      })
      .catch(() => undefined);
    adminApi<any[]>("/recruiters/pending")
      .then(setRecruiters)
      .catch(() => undefined);
  }, []);

  async function runAction() {
    if (!pending) return;
    const { action, jobIds } = pending;
    try {
      if (jobIds.length > 1) {
        const result = await adminApi<any>("/bulk/jobs/moderate", {
          method: "POST",
          body: JSON.stringify({
            job_ids: jobIds,
            action,
            reason: NEEDS_REASON.includes(action) ? reason : null,
            note: note || null,
          }),
        });
        setNotice(
          `${result.succeeded.length} of ${result.requested} jobs updated${
            result.failed.length ? `; ${result.failed.length} failed` : ""
          }.`
        );
      } else {
        const jobId = jobIds[0];
        const body = NEEDS_REASON.includes(action)
          ? JSON.stringify({ reason, note: note || null })
          : JSON.stringify({ note: note || null });
        await adminApi(`/jobs/${jobId}/${action}`, { method: "POST", body });
        setNotice(`Job #${jobId} ${action}d.`);
      }
      setPending(null);
      setNote("");
      load();
    } catch (e: any) {
      setError(e.message);
      setPending(null);
    }
  }

  async function decideRecruiter(userId: number, decision: "approve" | "reject") {
    try {
      await adminApi(`/recruiters/${userId}/${decision}`, { method: "POST" });
      setRecruiters(await adminApi<any[]>("/recruiters/pending"));
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <AdminShell title="Jobs & moderation" description="Review, approve, reject, suspend and restore listings.">
      {notice && <p className="muted">{notice}</p>}

      {recruiters.length > 0 && (
        <section className="section card">
          <h2>Recruiters awaiting approval</h2>
          {recruiters.map((r) => (
            <div className="row" key={r.id}>
              <span>
                <b>{r.full_name}</b> · {r.email}
              </span>
              <span className="jobcard-actions">
                <button className="linkbtn" type="button" onClick={() => decideRecruiter(r.id, "approve")}>
                  Approve
                </button>
                <button className="linkbtn danger" type="button" onClick={() => decideRecruiter(r.id, "reject")}>
                  Reject
                </button>
              </span>
            </div>
          ))}
        </section>
      )}

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
          placeholder="Search job title or organization"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search jobs"
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
          aria-label="Filter by job status"
        >
          <option value="">All statuses</option>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <label className="field-label">
          Created after
          <input
            className="field"
            type="date"
            value={createdFrom}
            onChange={(e) => {
              setOffset(0);
              setCreatedFrom(e.target.value ? `${e.target.value}T00:00:00` : "");
            }}
          />
        </label>
      </div>

      {selected.length > 0 && (
        <div className="bulkbar card">
          <span>{selected.length} selected</span>
          <div className="jobcard-actions">
            {(["approve", "reject", "suspend", "restore"] as Action[]).map((action) => (
              <button
                key={action}
                className="linkbtn"
                type="button"
                onClick={() => setPending({ action, jobIds: selected })}
              >
                Bulk {action}
              </button>
            ))}
          </div>
        </div>
      )}

      <AsyncState
        loading={loading}
        error={error}
        empty={!page || page.results.length === 0}
        emptyMessage="No jobs match these filters."
      >
        {page && (
          <>
            <table className="srctable">
              <caption className="muted">Job moderation queue</caption>
              <thead>
                <tr>
                  <th scope="col">
                    <span className="muted">Select</span>
                  </th>
                  <th scope="col">Title</th>
                  <th scope="col">Organization</th>
                  <th scope="col">Status</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Created</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {page.results.map((job) => (
                  <tr key={job.id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Select ${job.title}`}
                        checked={selected.includes(job.id)}
                        onChange={(e) =>
                          setSelected((prev) =>
                            e.target.checked ? [...prev, job.id] : prev.filter((id) => id !== job.id)
                          )
                        }
                      />
                    </td>
                    <td>
                      {job.title}
                      {job.moderation_note && (
                        <div className="muted">Internal note: {job.moderation_note}</div>
                      )}
                    </td>
                    <td>{job.organization}</td>
                    <td>
                      <span className={statusBadgeClass(job.status)}>{job.status}</span>
                    </td>
                    <td>{job.moderation_reason ? job.moderation_reason.replace(/_/g, " ") : "—"}</td>
                    <td>{formatDate(job.created_at)}</td>
                    <td>
                      <div className="jobcard-actions">
                        {job.status === "review" && (
                          <button
                            className="linkbtn"
                            type="button"
                            onClick={() => setPending({ action: "approve", jobIds: [job.id] })}
                          >
                            Approve
                          </button>
                        )}
                        {job.status !== "rejected" && (
                          <button
                            className="linkbtn danger"
                            type="button"
                            onClick={() => setPending({ action: "reject", jobIds: [job.id] })}
                          >
                            Reject
                          </button>
                        )}
                        {job.status === "published" && (
                          <button
                            className="linkbtn danger"
                            type="button"
                            onClick={() => setPending({ action: "suspend", jobIds: [job.id] })}
                          >
                            Suspend
                          </button>
                        )}
                        {(job.status === "suspended" || job.status === "rejected") && (
                          <button
                            className="linkbtn"
                            type="button"
                            onClick={() => setPending({ action: "restore", jobIds: [job.id] })}
                          >
                            Restore
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

      <ConfirmDialog
        open={!!pending}
        title={`${pending?.action ?? ""} ${pending && pending.jobIds.length > 1 ? `${pending.jobIds.length} jobs` : "this job"}?`}
        body={
          pending?.action === "suspend"
            ? "The listing will be removed from public search and candidate views immediately. Applications already made are preserved."
            : pending?.action === "reject"
              ? "The recruiter will see the structured reason. Your internal note is never shown to them."
              : pending?.action === "approve"
                ? "The listing will be published and visible to candidates."
                : "The listing will return to the status it held before it was suspended or rejected."
        }
        confirmLabel={`Confirm ${pending?.action ?? ""}`}
        reversible
        onConfirm={runAction}
        onCancel={() => setPending(null)}
      >
        {pending && NEEDS_REASON.includes(pending.action) && (
          <label className="field-label">
            Reason (shown to the recruiter)
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
          Internal note (optional — visible to platform administrators only)
          <input className="field" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
      </ConfirmDialog>
    </AdminShell>
  );
}
