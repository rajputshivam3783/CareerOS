"use client";

// V23.1 — header notification bell. A self-contained component so
// Nav.tsx only needs a one-line swap (plain "Notifications" link ->
// <NotificationBell />) rather than a redesign. Unread count and
// recent notifications both come from the backend (GET /notifications*
// endpoints) — never hardcoded or estimated client-side.

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Notification, fetchNotifications, fetchUnreadCount, markRead } from "@/lib/notifications";

const PRIORITY_ICON: Record<string, string> = { LOW: "", NORMAL: "", HIGH: "\u26a0", URGENT: "\u2757" };

export default function NotificationBell() {
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [recent, setRecent] = useState<Notification[] | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchUnreadCount()
      .then(setUnread)
      .catch(() => {});
  }, []);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  async function toggleOpen() {
    const next = !open;
    setOpen(next);
    if (next && recent === null) {
      try {
        const data = await fetchNotifications({ limit: 5 });
        setRecent(data.items);
        setUnread(data.unread_count);
      } catch {
        setRecent([]);
      }
    }
  }

  async function handleClickNotification(n: Notification) {
    if (!n.read) {
      try {
        await markRead(n.id);
        setUnread((u) => Math.max(0, u - 1));
        setRecent((list) => (list ? list.map((x) => (x.id === n.id ? { ...x, read: true } : x)) : list));
      } catch {
        // navigation still proceeds even if marking read failed
      }
    }
    if (n.action_url) location.href = n.action_url;
    setOpen(false);
  }

  return (
    <div className="notif-bell" ref={containerRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        className="linkbtn"
        onClick={toggleOpen}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
      >
        Notifications
        {unread > 0 && (
          <span className="badge" aria-hidden="true">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="notif-dropdown card" role="menu">
          <div className="row" style={{ marginBottom: 6 }}>
            <b style={{ fontSize: 14 }}>Notifications</b>
            <Link href="/notifications" className="linkbtn" style={{ fontSize: 13 }} onClick={() => setOpen(false)}>
              View all
            </Link>
          </div>

          {recent === null ? (
            <p className="muted" style={{ fontSize: 13 }}>
              Loading...
            </p>
          ) : recent.length === 0 ? (
            <p className="muted" style={{ fontSize: 13 }}>
              No notifications yet.
            </p>
          ) : (
            recent.map((n) => (
              <button
                key={n.id}
                className="notif-dropdown-item"
                onClick={() => handleClickNotification(n)}
                role="menuitem"
              >
                <span className={`notif-dot ${n.read ? "read" : "unread"}`} aria-hidden="true" />
                <span style={{ flex: 1, textAlign: "left" }}>
                  <b style={{ fontSize: 13 }}>
                    {PRIORITY_ICON[n.priority]} {n.title}
                  </b>
                  <p className="muted" style={{ margin: "2px 0 0", fontSize: 12 }}>
                    {new Date(n.created_at).toLocaleDateString()}
                  </p>
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
