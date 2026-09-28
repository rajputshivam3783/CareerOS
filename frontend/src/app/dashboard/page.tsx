"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { RankedRecommendation, fetchRecommendations } from "@/lib/recommendations";

const CATEGORIES = ["General", "EWS", "OBC", "SC", "ST"];

export default function Page() {
  const [d, setD] = useState<any>(null);
  const [recs, setRecs] = useState<RankedRecommendation[] | null>(null);
  const [p, setP] = useState<any>({
    location: "",
    highest_qualification: "",
    graduation_year: "",
    skills: "",
    preferred_roles: "",
    preferred_locations: "",
    date_of_birth: "",
    reservation_category: "General",
    is_pwd: false,
    candidate_searchable: false,
  });
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      setD(await api("/dashboard"));
      const x = await api("/profile");
      setP((v: any) => ({ ...v, ...x, date_of_birth: x.date_of_birth || "" }));
    } catch {
      location.href = "/login";
    }
    // Jobs For You preview — best-effort; the dashboard still works
    // fine if this fails (e.g. nothing to recommend yet).
    try {
      const r = await fetchRecommendations({ limit: 3 });
      setRecs(r.items);
    } catch {
      setRecs(null);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function save() {
    try {
      await api("/profile", {
        method: "PUT",
        body: JSON.stringify({
          ...p,
          graduation_year: p.graduation_year ? Number(p.graduation_year) : null,
          date_of_birth: p.date_of_birth || null,
        }),
      });
      setMsg("Profile saved");
      load();
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  return (
    <main className="container page">
      <span className="eyebrow">Personal OS</span>
      <h1>Dashboard</h1>
      <p><a href="/career-copilot">Ask the Career Copilot →</a></p>

      <div className="metrics">
        <div className="metric">
          <b>{d?.saved_jobs ?? "—"}</b>
          <span>Saved jobs</span>
        </div>
        <div className="metric">
          <b>{d?.applications ?? "—"}</b>
          <span>Applications</span>
        </div>
        <div className="metric">
          <b>{d?.alerts ?? "—"}</b>
          <span>Active alerts</span>
        </div>
        <div className="metric">
          <b>{d?.unread_notifications ?? "—"}</b>
          <span>Unread notifications</span>
        </div>
        <div className="metric">
          <b>{d?.upcoming_deadlines ?? "—"}</b>
          <span>Deadlines (next 7 days)</span>
        </div>
      </div>

      {d?.application_stats && (
        <div className="card">
          <div className="row">
            <h2>Application activity</h2>
            <a href="/applications">View all →</a>
          </div>
          <div className="metrics">
            <div className="metric">
              <b>{d.application_stats.total ?? 0}</b>
              <span>Total</span>
            </div>
            <div className="metric">
              <b>{d.application_stats.by_status?.APPLIED ?? 0}</b>
              <span>Applied</span>
            </div>
            <div className="metric">
              <b>{d.application_stats.by_status?.INTERVIEW ?? 0}</b>
              <span>Interviews</span>
            </div>
            <div className="metric">
              <b>{d.application_stats.by_status?.OFFER ?? 0}</b>
              <span>Offers</span>
            </div>
            <div className="metric">
              <b>{d.application_stats.by_status?.REJECTED ?? 0}</b>
              <span>Rejected</span>
            </div>
          </div>
          {d.application_stats.recent_activity?.length > 0 && (
            <div>
              <p className="muted" style={{ fontWeight: 700, marginBottom: 6 }}>Recent activity</p>
              {d.application_stats.recent_activity.slice(0, 5).map((entry: any, i: number) => (
                <p key={i} className="muted" style={{ fontSize: 13 }}>
                  {entry.job_title} at {entry.company} → {entry.new_status}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="card">
        <div className="row">
          <h2>Jobs for you</h2>
          <a href="/recommendations">See all →</a>
        </div>
        {recs === null || recs.length === 0 ? (
          <p className="muted">No recommendations yet — complete your profile below to get started.</p>
        ) : (
          <div className="tagrow">
            {recs.map((r) => (
              <a key={r.job_id} className="tag" href={`/jobs/${r.job_id}`}>
                {r.title} · {r.overall_score}%
              </a>
            ))}
          </div>
        )}
      </div>

      <div className="card form">
        <h2>Career profile</h2>
        <div className="grid2">
          <input
            className="field"
            placeholder="Location"
            value={p.location || ""}
            onChange={(e) => setP({ ...p, location: e.target.value })}
          />
          <input
            className="field"
            placeholder="Highest qualification"
            value={p.highest_qualification || ""}
            onChange={(e) => setP({ ...p, highest_qualification: e.target.value })}
          />
          <input
            className="field"
            type="number"
            placeholder="Graduation year"
            value={p.graduation_year || ""}
            onChange={(e) => setP({ ...p, graduation_year: e.target.value })}
          />
          <input
            className="field"
            placeholder="Skills: Java, Python, SQL"
            value={p.skills || ""}
            onChange={(e) => setP({ ...p, skills: e.target.value })}
          />
          <input
            className="field"
            placeholder="Preferred roles"
            value={p.preferred_roles || ""}
            onChange={(e) => setP({ ...p, preferred_roles: e.target.value })}
          />
          <input
            className="field"
            placeholder="Preferred locations"
            value={p.preferred_locations || ""}
            onChange={(e) => setP({ ...p, preferred_locations: e.target.value })}
          />
        </div>

        <h2>Eligibility details</h2>
        <p className="muted">
          Used only to check age eligibility for opportunities you view — optional, and entirely under your
          control.
        </p>
        <div className="grid2">
          <label className="field-label">
            Date of birth
            <input
              className="field"
              type="date"
              value={p.date_of_birth || ""}
              onChange={(e) => setP({ ...p, date_of_birth: e.target.value })}
            />
          </label>
          <label className="field-label">
            Reservation category (for an indicative age-relaxation estimate)
            <select
              className="field"
              value={p.reservation_category || "General"}
              onChange={(e) => setP({ ...p, reservation_category: e.target.value })}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={!!p.is_pwd}
              onChange={(e) => setP({ ...p, is_pwd: e.target.checked })}
            />
            Person with disability (PwD) relaxation applies
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={!!p.candidate_searchable}
              onChange={(e) => setP({ ...p, candidate_searchable: e.target.checked })}
            />
            Let recruiters discover my profile (skills, resume, education) even for jobs I haven&apos;t applied to
          </label>
        </div>

        {msg && <p>{msg}</p>}
        <button className="btn" onClick={save}>
          Save profile
        </button>
      </div>
    </main>
  );
}
