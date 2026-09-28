"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function Page() {
  const [team, setTeam] = useState<any[] | null>(null);
  const [err, setErr] = useState("");
  const [email, setEmail] = useState("");
  const [inviting, setInviting] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  async function load() {
    try {
      setTeam(await api("/recruiter/company/team"));
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function invite() {
    if (!email.trim()) return;
    setInviting(true);
    setErr("");
    try {
      await api("/recruiter/company/team/invite", { method: "POST", body: JSON.stringify({ email: email.trim() }) });
      setEmail("");
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setInviting(false);
    }
  }

  async function remove(memberId: number) {
    if (!window.confirm("Remove this recruiter from the team?")) return;
    setBusyId(memberId);
    setErr("");
    try {
      await api(`/recruiter/company/team/${memberId}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusyId(null);
    }
  }

  if (err && !team) return <main className="container page"><p className="error">{err}</p></main>;
  if (!team) return <main className="container page">Loading…</main>;

  return (
    <main className="container page">
      <span className="eyebrow">Company team</span>
      <div className="pagehead">
        <div>
          <h1>Recruiter team</h1>
          <p className="muted">
            Add other recruiter accounts to your company so they show up here. They need to have already
            registered and been granted a recruiter account.
          </p>
        </div>
        <a className="btn secondary" href="/recruiter/company">Company profile</a>
        <a className="btn secondary" href="/recruiter/company/email-templates">Email templates</a>
      </div>

      {err && <p className="error">{err}</p>}

      <div className="card form">
        <h2>Invite by email</h2>
        <div className="grid2">
          <input
            className="field"
            placeholder="recruiter@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <button className="btn" disabled={inviting} onClick={invite}>
            {inviting ? "Adding…" : "Add to team"}
          </button>
        </div>
      </div>

      <h2 className="section">Team members</h2>
      <div className="jobs">
        {team.map((m) => (
          <div className="card" key={m.id}>
            <div className="row">
              <span className="pill">{m.role}</span>
            </div>
            <h2>{m.name || "Recruiter"}</h2>
            <p className="muted">{m.email}</p>
            {m.role !== "owner" && (
              <button className="btn secondary danger" disabled={busyId === m.id} onClick={() => remove(m.id)}>
                {busyId === m.id ? "Removing…" : "Remove"}
              </button>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}
