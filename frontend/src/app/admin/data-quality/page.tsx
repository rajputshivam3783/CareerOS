"use client";
/**
 * V25.3 — admin data quality monitoring.
 *
 * Read-only over the inspected records. The single write this screen
 * performs is a triage decision (PUT .../triage), which records a
 * human judgement and never edits the flagged job, account or
 * application. There is no "fix" or "clean up" button anywhere here.
 */
import { useCallback, useEffect, useState } from "react";
import { AdminShell, AsyncState, Pager } from "@/components/admin/AdminShell";
import { Page, adminApi, formatDate, statusBadgeClass } from "@/lib/adminApi";

function severityBadge(severity: string) {
  switch (severity) {
    case "critical":
      return "badge badge-open";
    case "high":
      return "badge badge-open";
    case "medium":
      return "badge badge-paused";
    default:
      return "badge badge-disabled";
  }
}

export default function DataQualityPage() {
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [openRule, setOpenRule] = useState<string | null>(null);
  const [issues, setIssues] = useState<Page<any> | null>(null);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [triageDraft, setTriageDraft] = useState<Record<number, { state: string; note: string }>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setSummary(await adminApi("/data-quality"));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const loadIssues = useCallback(
    async (ruleId: string, pageOffset: number) => {
      setIssuesLoading(true);
      try {
        setIssues(await adminApi<Page<any>>(`/data-quality/issues/${ruleId}?limit=25&offset=${pageOffset}`));
      } catch (e: any) {
        setError(e.message);
      } finally {
        setIssuesLoading(false);
      }
    },
    []
  );

  function openRuleDetail(ruleId: string) {
    setOpenRule(ruleId);
    setOffset(0);
    loadIssues(ruleId, 0);
  }

  async function saveTriage(entityId: number) {
    if (!openRule) return;
    const draft = triageDraft[entityId] || { state: "acknowledged", note: "" };
    try {
      await adminApi(`/data-quality/issues/${openRule}/${entityId}/triage`, {
        method: "PUT",
        body: JSON.stringify({ state: draft.state, note: draft.note || null }),
      });
      loadIssues(openRule, offset);
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <AdminShell title="Data quality" description="Read-only checks over jobs, candidates and applications. Nothing here modifies production data.">
      <AsyncState loading={loading} error={error} empty={!summary} emptyMessage="No data quality summary available.">
        {summary && (
          <>
            <p className="muted">{summary.note}</p>
            <div className="statgrid">
              {Object.entries(summary.issues_by_severity || {}).map(([sev, count]) => (
                <div className="statcard" key={sev}>
                  <b>{String(count)}</b>
                  <span>{sev}</span>
                </div>
              ))}
            </div>

            <table className="srctable">
              <caption className="muted">Data quality rules</caption>
              <thead>
                <tr>
                  <th scope="col">Rule</th>
                  <th scope="col">Entity</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Count</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {summary.rules?.map((rule: any) => (
                  <tr key={rule.rule_id}>
                    <td>
                      {rule.title}
                      <div className="muted">{rule.description}</div>
                    </td>
                    <td>{rule.entity_type}</td>
                    <td><span className={severityBadge(rule.severity)}>{rule.severity}</span></td>
                    <td>{rule.count}</td>
                    <td>
                      {rule.count > 0 && (
                        <button className="linkbtn" type="button" onClick={() => openRuleDetail(rule.rule_id)}>
                          Review
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {summary.duplicate_jobs?.count > 0 && (
              <section className="section">
                <h2>{summary.duplicate_jobs.title}</h2>
                <p className="muted">{summary.duplicate_jobs.description}</p>
                <table className="srctable">
                  <thead>
                    <tr>
                      <th scope="col">Title</th>
                      <th scope="col">Organization</th>
                      <th scope="col">Occurrences</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.duplicate_jobs.groups.map((g: any, i: number) => (
                      <tr key={i}>
                        <td>{g.title}</td>
                        <td>{g.organization}</td>
                        <td>{g.occurrences}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
          </>
        )}
      </AsyncState>

      {openRule && (
        <section className="section card">
          <div className="row">
            <h2>Reviewing: {openRule}</h2>
            <button className="linkbtn" type="button" onClick={() => setOpenRule(null)}>Close</button>
          </div>
          <AsyncState
            loading={issuesLoading}
            error=""
            empty={!issues || issues.results.length === 0}
            emptyMessage="No flagged rows."
          >
            {issues && (
              <>
                <table className="srctable">
                  <thead>
                    <tr>
                      <th scope="col">Record</th>
                      <th scope="col">Triage state</th>
                      <th scope="col">Note</th>
                      <th scope="col">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {issues.results.map((row: any) => {
                      const draft = triageDraft[row.entity_id] || {
                        state: row.triage?.state || "open",
                        note: row.triage?.note || "",
                      };
                      return (
                        <tr key={row.entity_id}>
                          <td>{row.label}</td>
                          <td>
                            <select
                              className="field"
                              value={draft.state}
                              onChange={(e) =>
                                setTriageDraft({
                                  ...triageDraft,
                                  [row.entity_id]: { ...draft, state: e.target.value },
                                })
                              }
                            >
                              <option value="open">Open</option>
                              <option value="acknowledged">Acknowledged</option>
                              <option value="resolved">Resolved</option>
                              <option value="wont_fix">Won&apos;t fix</option>
                            </select>
                            {row.triage?.updated_at && (
                              <div className="muted">Updated {formatDate(row.triage.updated_at)}</div>
                            )}
                          </td>
                          <td>
                            <input
                              className="field"
                              value={draft.note}
                              onChange={(e) =>
                                setTriageDraft({
                                  ...triageDraft,
                                  [row.entity_id]: { ...draft, note: e.target.value },
                                })
                              }
                            />
                          </td>
                          <td>
                            <button className="linkbtn" type="button" onClick={() => saveTriage(row.entity_id)}>
                              Save
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <Pager
                  total={issues.total}
                  limit={issues.limit}
                  offset={issues.offset}
                  onChange={(next) => {
                    setOffset(next);
                    loadIssues(openRule, next);
                  }}
                />
              </>
            )}
          </AsyncState>
        </section>
      )}
    </AdminShell>
  );
}
