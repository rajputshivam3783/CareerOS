"use client";
/**
 * V25.2 — platform settings and announcements.
 *
 * Settings are typed and validated server-side; this screen renders a
 * control appropriate to each declared type and sends the value
 * through, rather than offering a free-text field that could write an
 * arbitrary value. Settings flagged sensitive require a full platform
 * administrator role and are confirmed before being applied.
 */
import { useCallback, useEffect, useState } from "react";
import { AdminShell, AsyncState, ConfirmDialog } from "@/components/admin/AdminShell";
import { adminApi, formatDate, statusBadgeClass } from "@/lib/adminApi";

type Setting = {
  key: string;
  value: boolean | number | string;
  value_type: "bool" | "int" | "str";
  default: boolean | number | string;
  description: string;
  sensitive: boolean;
  minimum: number | null;
  maximum: number | null;
  is_overridden: boolean;
  updated_at: string | null;
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<Setting[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<{ setting: Setting; value: boolean | number | string } | null>(null);

  const [announcements, setAnnouncements] = useState<any[]>([]);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [audience, setAudience] = useState("ALL");
  const [channel, setChannel] = useState("IN_APP");
  const [sendPending, setSendPending] = useState<any | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await adminApi<{ settings: Setting[] }>("/settings");
      setSettings(data.settings);
      setDrafts(Object.fromEntries(data.settings.map((s) => [s.key, String(s.value)])));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAnnouncements = useCallback(async () => {
    try {
      const page = await adminApi<{ results: any[] }>("/announcements?limit=10");
      setAnnouncements(page.results);
    } catch {
      // Announcements need CONTENT_MODERATION; an administrator
      // without it simply doesn't see this section.
      setAnnouncements([]);
    }
  }, []);

  useEffect(() => {
    load();
    loadAnnouncements();
  }, [load, loadAnnouncements]);

  function request(setting: Setting, value: boolean | number | string) {
    if (setting.sensitive) setPending({ setting, value });
    else apply(setting, value);
  }

  async function apply(setting: Setting, value: boolean | number | string) {
    try {
      await adminApi(`/settings/${setting.key}`, { method: "PUT", body: JSON.stringify({ value }) });
      setNotice(`${setting.key} updated.`);
      setPending(null);
      load();
    } catch (e: any) {
      setError(e.message);
      setPending(null);
    }
  }

  async function createAnnouncement(event: React.FormEvent) {
    event.preventDefault();
    try {
      await adminApi("/announcements", {
        method: "POST",
        body: JSON.stringify({ title, message, audience, channel }),
      });
      setTitle("");
      setMessage("");
      setNotice("Announcement saved as a draft. It has not been delivered to anyone yet.");
      loadAnnouncements();
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function sendAnnouncement() {
    if (!sendPending) return;
    try {
      const result = await adminApi<any>(`/announcements/${sendPending.id}/send`, { method: "POST" });
      setNotice(
        `Delivered to ${result.delivered} of ${result.targeted} recipients.${result.note ? ` ${result.note}` : ""}`
      );
      setSendPending(null);
      loadAnnouncements();
    } catch (e: any) {
      setError(e.message);
      setSendPending(null);
    }
  }

  return (
    <AdminShell title="Platform settings" description="Typed, validated configuration. Every change is audited.">
      {notice && <p className="muted">{notice}</p>}
      {error && <p className="error">{error}</p>}

      <AsyncState loading={loading} error="" empty={!settings} emptyMessage="No settings available.">
        {settings && (
          <table className="srctable">
            <caption className="muted">Platform configuration</caption>
            <thead>
              <tr>
                <th scope="col">Setting</th>
                <th scope="col">Value</th>
                <th scope="col">Description</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {settings.map((setting) => (
                <tr key={setting.key}>
                  <td>
                    {setting.key.replace(/_/g, " ")}
                    {setting.sensitive && <div className="badge badge-paused">sensitive</div>}
                  </td>
                  <td>
                    {setting.value_type === "bool" ? (
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={Boolean(setting.value)}
                          onChange={(e) => request(setting, e.target.checked)}
                        />
                        {setting.value ? "Enabled" : "Disabled"}
                      </label>
                    ) : (
                      <span className="tagadd">
                        <input
                          className="field"
                          type={setting.value_type === "int" ? "number" : "text"}
                          min={setting.minimum ?? undefined}
                          max={setting.maximum ?? undefined}
                          value={drafts[setting.key] ?? ""}
                          aria-label={setting.key}
                          onChange={(e) => setDrafts({ ...drafts, [setting.key]: e.target.value })}
                        />
                        <button
                          className="linkbtn"
                          type="button"
                          onClick={() =>
                            request(
                              setting,
                              setting.value_type === "int"
                                ? Number(drafts[setting.key])
                                : drafts[setting.key]
                            )
                          }
                        >
                          Save
                        </button>
                      </span>
                    )}
                  </td>
                  <td className="muted">{setting.description}</td>
                  <td className="muted">
                    {setting.is_overridden ? `Overridden ${formatDate(setting.updated_at)}` : "Default"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </AsyncState>

      <section className="section">
        <h2>Platform announcements</h2>
        <p className="muted">
          Announcements are created as drafts and deliver nothing until they are explicitly sent. Email
          delivery additionally requires the announcement_email_enabled setting above.
        </p>
        <form className="card form" onSubmit={createAnnouncement}>
          <label className="field-label">
            Title
            <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} required />
          </label>
          <label className="field-label">
            Message
            <textarea
              className="field"
              rows={4}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              required
            />
          </label>
          <div className="row">
            <label className="field-label">
              Audience
              <select className="field" value={audience} onChange={(e) => setAudience(e.target.value)}>
                <option value="ALL">Everyone</option>
                <option value="CANDIDATES">Candidates</option>
                <option value="RECRUITERS">Recruiters</option>
                <option value="ORGANIZATION_ADMINS">Organization owners and admins</option>
                <option value="PLATFORM_ADMINS">Platform administrators</option>
              </select>
            </label>
            <label className="field-label">
              Channel
              <select className="field" value={channel} onChange={(e) => setChannel(e.target.value)}>
                <option value="IN_APP">In-app only</option>
                <option value="BOTH">In-app and email</option>
                <option value="EMAIL">Email only</option>
              </select>
            </label>
          </div>
          <button className="btn" type="submit">
            Save draft
          </button>
        </form>

        {announcements.length > 0 && (
          <table className="srctable">
            <thead>
              <tr>
                <th scope="col">Title</th>
                <th scope="col">Audience</th>
                <th scope="col">Status</th>
                <th scope="col">Delivered</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {announcements.map((row) => (
                <tr key={row.id}>
                  <td>{row.title}</td>
                  <td>{row.audience}</td>
                  <td>
                    <span className={statusBadgeClass(row.status)}>{row.status}</span>
                  </td>
                  <td>{row.recipient_count}</td>
                  <td>
                    {row.status === "DRAFT" && (
                      <button className="linkbtn" type="button" onClick={() => setSendPending(row)}>
                        Send
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <ConfirmDialog
        open={!!pending}
        title="Change this platform setting?"
        body={`${pending?.setting.key.replace(/_/g, " ")} will be set to "${String(pending?.value)}". This affects the whole platform and is recorded in the audit trail.`}
        confirmLabel="Apply change"
        reversible
        onConfirm={() => pending && apply(pending.setting, pending.value)}
        onCancel={() => setPending(null)}
      />

      <ConfirmDialog
        open={!!sendPending}
        title="Send this announcement?"
        body={`"${sendPending?.title}" will be delivered to the ${sendPending?.audience} audience. This cannot be undone, and the announcement cannot be sent twice.`}
        confirmLabel="Send announcement"
        onConfirm={sendAnnouncement}
        onCancel={() => setSendPending(null)}
      />
    </AdminShell>
  );
}
