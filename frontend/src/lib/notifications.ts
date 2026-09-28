// V23.1 — thin typed wrapper around /notifications/* (new V23.1
// endpoints in app/api/notifications.py, plus the existing V19.4
// read/read-all/delete endpoints in app/api/notification_engine.py —
// all operate on the same underlying table, so they're grouped here
// together rather than split across two lib files).

import { api } from "@/lib/api";

export const NOTIFICATION_CATEGORIES = ["JOB", "APPLICATION", "INTERVIEW", "DEADLINE", "RECRUITER", "AI", "SYSTEM"] as const;
export type NotificationCategory = (typeof NOTIFICATION_CATEGORIES)[number];

export const NOTIFICATION_PRIORITIES = ["LOW", "NORMAL", "HIGH", "URGENT"] as const;
export type NotificationPriority = (typeof NOTIFICATION_PRIORITIES)[number];

export interface Notification {
  id: number;
  type: string;
  category: NotificationCategory | null;
  title: string;
  message: string;
  priority: NotificationPriority;
  read: boolean;
  read_at: string | null;
  action_url: string | null;
  metadata: Record<string, unknown> | null;
  job_id: number | null;
  created_at: string;
  updated_at: string | null;
}

export interface NotificationList {
  items: Notification[];
  total: number;
  unread_count: number;
  has_more: boolean;
}

export async function fetchNotifications(params: {
  unread_only?: boolean;
  category?: NotificationCategory;
  priority?: NotificationPriority;
  limit?: number;
  offset?: number;
} = {}): Promise<NotificationList> {
  const query = new URLSearchParams();
  if (params.unread_only) query.set("unread_only", "true");
  if (params.category) query.set("category", params.category);
  if (params.priority) query.set("priority", params.priority);
  query.set("limit", String(params.limit ?? 20));
  query.set("offset", String(params.offset ?? 0));
  return api(`/notifications?${query.toString()}`);
}

export async function fetchUnreadCount(): Promise<number> {
  const result: { unread_count: number } = await api("/notifications/unread-count");
  return result.unread_count;
}

export async function markRead(id: number): Promise<Notification> {
  return api(`/notifications/${id}/read`, { method: "POST" });
}

export async function markUnread(id: number): Promise<Notification> {
  return api(`/notifications/${id}/unread`, { method: "POST" });
}

export async function markAllRead(): Promise<{ marked_read: number }> {
  return api("/notifications/read-all", { method: "POST" });
}

export async function deleteNotification(id: number): Promise<void> {
  await api(`/notifications/${id}`, { method: "DELETE" });
}
