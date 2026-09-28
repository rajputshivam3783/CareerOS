"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5000+"];

const EMPTY_COMPANY = {
  name: "",
  website: "",
  logo_url: "",
  banner_url: "",
  description: "",
  industry: "",
  company_size: "",
  founded_year: "",
  location: "",
  linkedin_url: "",
  twitter_url: "",
  facebook_url: "",
  instagram_url: "",
};

const EMPTY_BRANCH = { branch_name: "", location: "", address: "", is_headquarters: false };

const STATUS_LABEL: Record<string, string> = {
  unverified: "Not submitted",
  pending: "Pending review",
  verified: "Verified",
  rejected: "Rejected",
};

export default function Page() {
  const [form, setForm] = useState<any>(EMPTY_COMPANY);
  const [org, setOrg] = useState<any>(null);
  const [branches, setBranches] = useState<any[]>([]);
  const [branchForm, setBranchForm] = useState<any>(EMPTY_BRANCH);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const existing = await api("/recruiter/company");
      setOrg(existing);
      setForm({ ...EMPTY_COMPANY, ...existing, founded_year: existing.founded_year ?? "" });
      setBranches(await api("/recruiter/company/branches"));
    } catch {
      // No company profile yet — that's fine, the form starts empty.
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function save() {
    setErr("");
    setMsg("");
    try {
      const body = {
        ...form,
        founded_year: form.founded_year ? Number(form.founded_year) : null,
        website: form.website || null,
        logo_url: form.logo_url || null,
        banner_url: form.banner_url || null,
        description: form.description || null,
        industry: form.industry || null,
        company_size: form.company_size || null,
        location: form.location || null,
        linkedin_url: form.linkedin_url || null,
        twitter_url: form.twitter_url || null,
        facebook_url: form.facebook_url || null,
        instagram_url: form.instagram_url || null,
      };
      const saved = await api("/recruiter/company", { method: "PUT", body: JSON.stringify(body) });
      setOrg(saved);
      setMsg(org ? "Company profile updated." : "Company profile created.");
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function addBranch() {
    setErr("");
    try {
      await api("/recruiter/company/branches", { method: "POST", body: JSON.stringify(branchForm) });
      setBranchForm(EMPTY_BRANCH);
      setBranches(await api("/recruiter/company/branches"));
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function removeBranch(id: number) {
    try {
      await api(`/recruiter/company/branches/${id}`, { method: "DELETE" });
      setBranches(branches.filter((b) => b.id !== id));
    } catch (e: any) {
      setErr(e.message);
    }
  }

  if (loading) return <main className="container page">Loading…</main>;

  return (
    <main className="container page">
      <span className="eyebrow">Company module</span>
      <div className="pagehead">
        <div>
          <h1>Company profile</h1>
          <p className="muted">
            This is what candidates see when they view your jobs — logo, banner, description and locations.
          </p>
        </div>
        {org && (
          <span className={org.verification_status === "verified" ? "verified" : "chip"}>
            {STATUS_LABEL[org.verification_status] || org.verification_status}
          </span>
        )}
      </div>

      <div className="actions" style={{ marginTop: 10 }}>
        <a className="btn secondary" href="/recruiter/company/team">Manage team</a>
        <a className="btn secondary" href="/recruiter/company/email-templates">Email templates</a>
      </div>

      {err && <p className="error">{err}</p>}
      {msg && <p className="muted">{msg}</p>}

      <div className="card form">
        <h2>Profile details</h2>
        <div className="grid2">
          <input
            className="field"
            placeholder="Company name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            className="field"
            placeholder="Website (https://...)"
            value={form.website}
            onChange={(e) => setForm({ ...form, website: e.target.value })}
          />
          <input
            className="field"
            placeholder="Logo URL"
            value={form.logo_url}
            onChange={(e) => setForm({ ...form, logo_url: e.target.value })}
          />
          <input
            className="field"
            placeholder="Banner URL"
            value={form.banner_url}
            onChange={(e) => setForm({ ...form, banner_url: e.target.value })}
          />
          <input
            className="field"
            placeholder="Industry"
            value={form.industry}
            onChange={(e) => setForm({ ...form, industry: e.target.value })}
          />
          <select
            className="field"
            value={form.company_size}
            onChange={(e) => setForm({ ...form, company_size: e.target.value })}
          >
            <option value="">Company size</option>
            {COMPANY_SIZES.map((s) => (
              <option key={s} value={s}>
                {s} employees
              </option>
            ))}
          </select>
          <input
            className="field"
            placeholder="Founded year"
            type="number"
            value={form.founded_year}
            onChange={(e) => setForm({ ...form, founded_year: e.target.value })}
          />
          <input
            className="field"
            placeholder="Headquarters location"
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
          />
          <input
            className="field"
            placeholder="LinkedIn URL"
            value={form.linkedin_url}
            onChange={(e) => setForm({ ...form, linkedin_url: e.target.value })}
          />
          <input
            className="field"
            placeholder="Twitter / X URL"
            value={form.twitter_url}
            onChange={(e) => setForm({ ...form, twitter_url: e.target.value })}
          />
          <input
            className="field"
            placeholder="Facebook URL"
            value={form.facebook_url}
            onChange={(e) => setForm({ ...form, facebook_url: e.target.value })}
          />
          <input
            className="field"
            placeholder="Instagram URL"
            value={form.instagram_url}
            onChange={(e) => setForm({ ...form, instagram_url: e.target.value })}
          />
        </div>
        <textarea
          className="field"
          rows={5}
          placeholder="Company description"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
        <button className="btn" onClick={save}>
          {org ? "Save changes" : "Create company profile"}
        </button>
        {org && org.verification_status === "verified" && (
          <p className="muted">Material edits will send this profile back for re-verification.</p>
        )}
      </div>

      {org && (
        <>
          <h2 className="section">Branches</h2>
          <div className="card form">
            <div className="grid2">
              <input
                className="field"
                placeholder="Branch name (e.g. Mumbai Office)"
                value={branchForm.branch_name}
                onChange={(e) => setBranchForm({ ...branchForm, branch_name: e.target.value })}
              />
              <input
                className="field"
                placeholder="Location (city)"
                value={branchForm.location}
                onChange={(e) => setBranchForm({ ...branchForm, location: e.target.value })}
              />
            </div>
            <input
              className="field"
              placeholder="Full address (optional)"
              value={branchForm.address}
              onChange={(e) => setBranchForm({ ...branchForm, address: e.target.value })}
            />
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={branchForm.is_headquarters}
                onChange={(e) => setBranchForm({ ...branchForm, is_headquarters: e.target.checked })}
              />
              This is the headquarters
            </label>
            <button className="btn secondary" onClick={addBranch}>
              Add branch
            </button>
          </div>

          <div className="jobs">
            {branches.map((b) => (
              <div className="card" key={b.id}>
                <div className="row">
                  {b.is_headquarters && <span className="pill">HQ</span>}
                </div>
                <h2>{b.branch_name}</h2>
                <p className="muted">{b.location}</p>
                {b.address && <p className="muted">{b.address}</p>}
                <button className="linkbtn danger" onClick={() => removeBranch(b.id)}>
                  Remove
                </button>
              </div>
            ))}
            {!branches.length && <p className="empty">No branches added yet.</p>}
          </div>
        </>
      )}
    </main>
  );
}
