"use client";


// V22.2 — Smart Application Dashboard. Owns all fetching (single
// source of truth for both the Kanban and List views, which are
// otherwise purely presentational — see KanbanBoard.tsx). Filters and
// the current view are reflected in the URL (spec: "so the page can
// be refreshed/shared without losing the current view state").

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import AddApplicationForm from "@/components/applications/AddApplicationForm";
import ApplicationCard from "@/components/applications/ApplicationCard";
import DashboardStats from "@/components/applications/DashboardStats";
import KanbanBoard from "@/components/applications/KanbanBoard";
import RecentActivity from "@/components/applications/RecentActivity";
import UpcomingDeadlines from "@/components/applications/UpcomingDeadlines";
import { isSignedIn } from "@/lib/bookmarks";
import {
  Application,
  ApplicationDashboard,
  STATUS_LABELS,
  STATUS_VALUES,
  deleteApplication,
  fetchApplicationDashboard,
  fetchApplications,
} from "@/lib/applications";

const KANBAN_FETCH_LIMIT = 200; // PERFORMANCE: "do not load thousands of applications unnecessarily"
const LIST_PAGE_SIZE = 20;

type View = "kanban" | "list";

export default function ApplicationsClient() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const view = (searchParams.get("view") as View) || "kanban";
  const statusFilter = searchParams.get("status") || "";
  const companyFilter = searchParams.get("company") || "";
  const sourceFilter = searchParams.get("source") || "";
  const dateFrom = searchParams.get("date_from") || "";
  const dateTo = searchParams.get("date_to") || "";
  const page = Number(searchParams.get("page") || "1");

  const [searchInput, setSearchInput] = useState(searchParams.get("search") || "");
  const [search, setSearch] = useState(searchParams.get("search") || "");

  const [dashboard, setDashboard] = useState<ApplicationDashboard | null>(null);
  const [items, setItems] = useState<Application[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);

  // SEARCH: debounce so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  const updateParams = useCallback(
    (patch: Record<string, string | number | null>) => {
      const usp = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === "") usp.delete(key);
        else usp.set(key, String(value));
      }
      router.replace(`/applications?${usp.toString()}`, { scroll: false });
    },
    [router, searchParams]
  );

  // Keep the URL's `search` param in sync once the debounce settles.
  useEffect(() => {
    if (search !== (searchParams.get("search") || "")) updateParams({ search: search || null, page: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const loadDashboard = useCallback(async () => {
    try {
      setDashboard(await fetchApplicationDashboard());
    } catch (e: any) {
      setError(e.message || "Could not load dashboard statistics.");
    }
  }, []);

  const loadItems = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const filters = {
        status: view === "list" && statusFilter ? (statusFilter as any) : undefined,
        company: companyFilter || undefined,
        source: sourceFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        search: search || undefined,
      };
      if (view === "kanban") {
        const resp = await fetchApplications({ ...filters, limit: KANBAN_FETCH_LIMIT, offset: 0 });
        setItems(resp.items);
        setTotal(resp.total);
      } else {
        const resp = await fetchApplications({ ...filters, limit: LIST_PAGE_SIZE, offset: (page - 1) * LIST_PAGE_SIZE });
        setItems(resp.items);
        setTotal(resp.total);
      }
    } catch (e: any) {
      setError(e.message || "Could not load applications.");
    } finally {
      setLoading(false);
    }
  }, [view, statusFilter, companyFilter, sourceFilter, dateFrom, dateTo, search, page]);

  useEffect(() => {
    if (!isSignedIn()) {
      location.href = "/login";
      return;
    }
    loadDashboard();
  }, [loadDashboard]);

  useEffect(() => {
    if (!isSignedIn()) return;
    loadItems();
  }, [loadItems]);

  async function handleDelete(id: number) {
    if (!confirm("Delete this application? This cannot be undone.")) return;
    try {
      await deleteApplication(id);
      setItems((prev) => prev.filter((a) => a.id !== id));
      setTotal((t) => Math.max(0, t - 1));
      loadDashboard();
    } catch (e: any) {
      setError(e.message || "Could not delete this application.");
    }
  }

  function handleChanged(updated: Application) {
    setItems((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
    loadDashboard();
  }

  const hasFilters = !!(statusFilter || companyFilter || sourceFilter || dateFrom || dateTo || search);

  function clearFilters() {
    setSearchInput("");
    router.replace("/applications?view=" + view, { scroll: false });
  }

  const totalPages = Math.max(1, Math.ceil(total / LIST_PAGE_SIZE));

  return (
    <main className="container page">
      <div className="pagehead">
        <div>
          <span className="eyebrow">Application tracking</span>
          <h1>Your Applications</h1>
          <p className="muted">Track every application from saved to offer, in one place.</p>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => setShowAddForm(true)}>
            Add Application
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {showAddForm && (
        <AddApplicationForm
          onCreated={() => {
            setShowAddForm(false);
            loadDashboard();
            loadItems();
          }}
          onCancel={() => setShowAddForm(false)}
        />
      )}

      {dashboard && <DashboardStats dashboard={dashboard} />}

      <div className="grid2" style={{ marginTop: 16 }}>
        {dashboard && <UpcomingDeadlines items={dashboard.upcoming_deadlines} />}
        {dashboard && <RecentActivity items={dashboard.recent_activity} />}
      </div>

      <div className="pagehead" style={{ marginTop: 28, marginBottom: 0 }}>
        <div className="viewtoggle" role="tablist" aria-label="Application view">
          <button
            role="tab"
            aria-selected={view === "kanban"}
            className={view === "kanban" ? "active" : ""}
            onClick={() => updateParams({ view: "kanban", page: null })}
          >
            KANBAN
          </button>
          <button
            role="tab"
            aria-selected={view === "list"}
            className={view === "list" ? "active" : ""}
            onClick={() => updateParams({ view: "list", page: null })}
          >
            LIST
          </button>
        </div>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="filters" role="search">
          <input
            className="field"
            style={{ minWidth: 220 }}
            placeholder="Search company, job title, or location..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            aria-label="Search applications"
          />
          {view === "list" && (
            <select className="field" value={statusFilter} onChange={(e) => updateParams({ status: e.target.value || null, page: null })} aria-label="Filter by status">
              <option value="">All statuses</option>
              {STATUS_VALUES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          )}
          <input
            className="field"
            placeholder="Company"
            value={companyFilter}
            onChange={(e) => updateParams({ company: e.target.value || null, page: null })}
            aria-label="Filter by company"
          />
          <input
            className="field"
            placeholder="Source"
            value={sourceFilter}
            onChange={(e) => updateParams({ source: e.target.value || null, page: null })}
            aria-label="Filter by source"
          />
          <label className="field-label" style={{ margin: 0 }}>
            <span className="sr-only">From date</span>
            <input type="date" className="field" value={dateFrom} onChange={(e) => updateParams({ date_from: e.target.value || null, page: null })} />
          </label>
          <label className="field-label" style={{ margin: 0 }}>
            <span className="sr-only">To date</span>
            <input type="date" className="field" value={dateTo} onChange={(e) => updateParams({ date_to: e.target.value || null, page: null })} />
          </label>
          {hasFilters && (
            <button className="linkbtn" onClick={clearFilters}>
              Clear Filters
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <p className="muted" style={{ marginTop: 20 }}>
          Loading…
        </p>
      ) : items.length === 0 ? (
        <div className="empty">
          {hasFilters ? (
            <>
              <p>No applications found for these filters.</p>
              <button className="btn secondary" onClick={clearFilters}>
                Clear Filters
              </button>
            </>
          ) : (
            <>
              <p>No applications yet.</p>
              <div className="actions" style={{ justifyContent: "center" }}>
                <button className="btn" onClick={() => setShowAddForm(true)}>
                  Add Application
                </button>
                <a className="btn secondary" href="/jobs">
                  Browse Jobs
                </a>
              </div>
            </>
          )}
        </div>
      ) : view === "kanban" ? (
        <KanbanBoard items={items} onItemsChange={setItems} onError={setError} onDelete={handleDelete} />
      ) : (
        <>
          <div className="jobs" style={{ marginTop: 16 }}>
            {items.map((a) => (
              <ApplicationCard key={a.id} application={a} onChanged={handleChanged} onError={setError} onDelete={handleDelete} />
            ))}
          </div>
          {totalPages > 1 && (
            <div className="actions" style={{ justifyContent: "center", marginTop: 20 }}>
              <button className="btn secondary" disabled={page <= 1} onClick={() => updateParams({ page: page - 1 })}>
                Previous
              </button>
              <span className="muted" style={{ alignSelf: "center" }}>
                Page {page} of {totalPages}
              </span>
              <button className="btn secondary" disabled={page >= totalPages} onClick={() => updateParams({ page: page + 1 })}>
                Next
              </button>
            </div>
          )}
        </>
      )}
    </main>
  );
}
