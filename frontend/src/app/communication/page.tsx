"use client";
// V23.4 — Communication Center. One page pulling together V23.1
// notifications, V23.3 job alerts, and this version's own
// summary/actions/upcoming/reminders endpoints (app/api/communication.py)
// — see that router's own docstring. The Notifications and Job Alerts
// tabs deliberately reuse the existing lib functions (src/lib/notifications.ts,
// src/lib/jobAlerts.ts) and link out to their full existing pages
// rather than re-implementing that state here (spec: "Do NOT create
// duplicate storage systems" extends, in the frontend, to not
// re-fetching/re-rendering the same data two different ways).
import { useEffect, useState } from "react";
import Link from "next/link";
import { formatApiError } from "@/lib/api";
import {
  ActionItem, CommunicationSummary, UpcomingBuckets,
  fetchActionRequired, fetchCommunicationSummary, fetchUpcoming,
} from "@/lib/communication";
import { Notification, fetchNotifications, markAllRead, markRead } from "@/lib/notifications";
import { JobAlert, listJobAlerts } from "@/lib/jobAlerts";

type Tab = "overview" | "notifications" | "upcoming" | "actions" | "alerts" | "preferences";
const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "notifications", label: "Notifications" },
  { key: "upcoming", label: "Upcoming" },
  { key: "actions", label: "Action Required" },
  { key: "alerts", label: "Job Alerts" },
  { key: "preferences", label: "Preferences" },
];

const PRIORITY_BADGE: Record<string, string> = {
  URGENT: "badge-negative", HIGH: "badge-progress", NORMAL: "badge-active", LOW: "badge-disabled",
};

function PriorityBadge({ priority }: { priority: string }) {
  return <span className={`badge ${PRIORITY_BADGE[priority] || "badge-disabled"}`}>{priority}</span>;
}

function SummaryCards({ summary }: { summary: CommunicationSummary }) {
  const cards: { label: string; value: number; href: string }[] = [
    { label: "Unread notifications", value: summary.unread_notifications, href: "" },
    { label: "Upcoming interviews", value: summary.upcoming_interviews, href: "" },
    { label: "Upcoming deadlines", value: summary.upcoming_deadlines, href: "" },
    { label: "Overdue deadlines", value: summary.overdue_deadlines, href: "" },
    { label: "Overdue tasks", value: summary.overdue_tasks, href: "" },
    { label: "Applications needing attention", value: summary.applications_needing_attention, href: "" },
    { label: "New job matches", value: summary.new_job_matches, href: "" },
  ];
  return (
    <div className="statgrid">
      {cards.map((c) => (
        <div className="statcard" key={c.label}>
          <b>{c.value}</b>
          <span>{c.label}</span>
        </div>
      ))}
    </div>
  );
}

function ActionList({ actions }: { actions: ActionItem[] }) {
  if (!actions.length) return <div className="empty">Nothing needs your attention right now.</div>;
  return (
    <div className="qlist">
      {actions.map((a, i) => (
        <div className="qitem" key={`${a.kind}-${a.action_url}-${i}`} style={{ alignItems: "flex-start" }}>
          <div>
            <div className="row" style={{ gap: 8, marginBottom: 4 }}>
              <PriorityBadge priority={a.priority} />
              <span className="muted" style={{ fontSize: 12 }}>{a.source}</span>
              {a.due_date && <span className="muted" style={{ fontSize: 12 }}>Due {a.due_date}</span>}
            </div>
            <b>{a.title}</b>
            <p className="muted" style={{ margin: "4px 0 0" }}>{a.reason}</p>
          </div>
          <Link className="linkbtn" href={a.action_url}>View</Link>
        </div>
      ))}
    </div>
  );
}

function UpcomingTimeline({ upcoming }: { upcoming: UpcomingBuckets }) {
  const sections: { key: keyof UpcomingBuckets; label: string }[] = [
    { key: "TODAY", label: "Today" }, { key: "TOMORROW", label: "Tomorrow" },
    { key: "THIS_WEEK", label: "This week" }, { key: "LATER", label: "Later" },
  ];
  const anyItems = sections.some((s) => upcoming[s.key].length > 0);
  if (!anyItems) return <div className="empty">Nothing upcoming in this window.</div>;
  return (
    <div>
      {sections.map((s) => upcoming[s.key].length > 0 && (
        <div key={s.key} className="section">
          <h2>{s.label}</h2>
          <div className="qlist">
            {upcoming[s.key].map((item, i) => (
              <div className="qitem" key={`${s.key}-${i}`}>
                <div>
                  <span className="pill">{item.type}</span>{" "}
                  <b>{item.title}</b>
                  <div className="muted" style={{ fontSize: 12 }}>{item.date}{item.time ? ` · ${item.time}` : ""}</div>
                </div>
                <Link className="linkbtn" href={item.action_url}>View</Link>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function NotificationsTab() {
  const [items, setItems] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try {
      const resp = await fetchNotifications({ limit: 10 });
      setItems(resp.items);
    } catch (e: any) {
      setError(formatApiError(e.message, "Couldn't load notifications"));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="muted">Most recent notifications, across every category.</span>
        <div className="actions">
          <button className="linkbtn" onClick={async () => { await markAllRead(); load(); }}>Mark all as read</button>
          <Link className="btn secondary" href="/notifications">Open full Notification Center</Link>
        </div>
      </div>
      {loading && <p className="loading">Loading…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !items.length && <div className="empty">You're all caught up.</div>}
      <div className="qlist">
        {items.map((n) => (
          <div className="qitem" key={n.id}>
            <div>
              {n.category && <span className="pill">{n.category}</span>} <b>{n.title}</b>
              <p className="muted" style={{ margin: "4px 0 0" }}>{n.message}</p>
            </div>
            <div className="actions">
              {n.action_url && <Link className="linkbtn" href={n.action_url}>View</Link>}
              {!n.read && <button className="linkbtn" onClick={async () => { await markRead(n.id); load(); }}>Mark as read</button>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function JobAlertsTab() {
  const [alerts, setAlerts] = useState<JobAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    listJobAlerts()
      .then(setAlerts)
      .catch((e) => setError(formatApiError(e.message, "Couldn't load job alerts")))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="muted">Your Smart Job Alerts and their recent matches.</span>
        <Link className="btn secondary" href="/job-alerts">Manage alerts</Link>
      </div>
      {loading && <p className="loading">Loading…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !alerts.length && <div className="empty">You haven't created any job alerts yet.</div>}
      <div className="qlist">
        {alerts.map((a) => (
          <div className="qitem" key={a.id}>
            <div>
              <span className={`badge ${a.enabled ? "badge-active" : "badge-disabled"}`}>{a.enabled ? "Active" : "Paused"}</span>{" "}
              <b>{a.name}</b>
              <div className="muted" style={{ fontSize: 12 }}>
                {a.frequency} · {a.last_match_count} match(es) · last run {a.last_run_at ? new Date(a.last_run_at).toLocaleString() : "never"}
              </div>
            </div>
            <div className="actions">
              <Link className="linkbtn" href={`/job-alerts/${a.id}`}>View Jobs</Link>
              <Link className="linkbtn" href="/job-alerts">Manage Alert</Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Page() {
  const [tab, setTab] = useState<Tab>("overview");
  const [summary, setSummary] = useState<CommunicationSummary | null>(null);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [upcoming, setUpcoming] = useState<UpcomingBuckets | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    Promise.all([fetchCommunicationSummary(), fetchActionRequired(), fetchUpcoming()])
      .then(([s, a, u]) => { setSummary(s); setActions(a.actions); setUpcoming(u); })
      .catch((e) => {
        if (String(e.message || "").includes("401")) { location.href = "/login"; return; }
        setError(formatApiError(e.message, "Couldn't load the Communication Center"));
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="container page">
      <div className="pagehead">
        <div>
          <span className="eyebrow">Communication center</span>
          <h1>Communication</h1>
        </div>
      </div>

      <div className="filters">
        {TABS.map((t) => (
          <button key={t.key} className={`chip ${tab === t.key ? "chip-active" : ""}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {loading && <p className="loading">Loading…</p>}
      {error && <p className="error">{error}</p>}

      {!loading && !error && (
        <div className="card" style={{ marginTop: 18 }}>
          {tab === "overview" && summary && (
            <div>
              <SummaryCards summary={summary} />
              <h2 style={{ marginTop: 24 }}>Action Required</h2>
              <ActionList actions={actions.slice(0, 5)} />
              {actions.length > 5 && (
                <p style={{ marginTop: 8 }}>
                  <button className="linkbtn" onClick={() => setTab("actions")}>View all {actions.length} actions</button>
                </p>
              )}
            </div>
          )}
          {tab === "notifications" && <NotificationsTab />}
          {tab === "upcoming" && upcoming && <UpcomingTimeline upcoming={upcoming} />}
          {tab === "actions" && <ActionList actions={actions} />}
          {tab === "alerts" && <JobAlertsTab />}
          {tab === "preferences" && (
            <div>
              <p className="muted">
                Job alerts, application updates, interview reminders, deadline reminders, AI recommendations, and the
                daily digest — each with its own in-app/email channel — are all managed on one preferences page.
              </p>
              <Link className="btn" href="/notifications/preferences">Open notification preferences</Link>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
