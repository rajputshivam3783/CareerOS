"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function Page() {
  const [profile, setProfile] = useState<any>(null);
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState(false);
  const [saving, setSaving] = useState(false);

  async function load() {
    try {
      const p = await api("/recruiter/profile");
      setProfile(p);
      setFullName(p.full_name || "");
      setPhone(p.phone || "");
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function save() {
    setSaving(true);
    setErr("");
    setOk(false);
    try {
      await api("/recruiter/profile", {
        method: "PATCH",
        body: JSON.stringify({ full_name: fullName.trim(), phone: phone.trim() || null }),
      });
      setOk(true);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (err && !profile) return <main className="container page"><p className="error">{err}</p></main>;
  if (!profile) return <main className="container page">Loading…</main>;

  return (
    <main className="container page">
      <span className="eyebrow">Recruiter profile</span>
      <div className="pagehead">
        <div>
          <h1>Your profile</h1>
          <p className="muted">
            Your name and phone number are yours to update. Your email and account role are managed by
            authentication and can&apos;t be changed here.
          </p>
        </div>
        <a className="btn secondary" href="/recruiter">Back to workspace</a>
      </div>

      {err && <p className="error">{err}</p>}
      {ok && <p className="muted">Saved.</p>}

      <div className="card form">
        <h2>Identity</h2>
        <div className="grid2">
          <input className="field" placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          <input className="field" placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
          <input className="field" value={profile.email} disabled />
          <input className="field" value={profile.role} disabled />
        </div>
        <button className="btn" disabled={saving} onClick={save}>
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>

      <h2 className="section">Company</h2>
      <div className="card">
        <p><b>{profile.company_name || "No company yet"}</b></p>
        {profile.company_role && <p className="muted">Your role on this company: {profile.company_role}</p>}
        <a className="btn secondary" href="/recruiter/company">Manage company profile</a>
      </div>
    </main>
  );
}
