"use client";

import { useEffect, useState } from "react";
import { API } from "@/lib/api";

export default function Page() {
  const [companies, setCompanies] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      params.set("limit", "40");
      const r = await fetch(`${API}/companies?${params.toString()}`);
      if (!r.ok) throw new Error("Could not load companies right now.");
      setCompanies(await r.json());
    } catch (e: any) {
      setError(e.message || "Something went wrong.");
      setCompanies([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="container page">
      <div className="pagehead">
        <div>
          <span className="eyebrow">Employer directory</span>
          <h1>Companies hiring on CareerOS</h1>
        </div>
        <div className="search">
          <input
            className="field"
            placeholder="Search companies..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
          />
          <button className="btn" onClick={load}>
            Search
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Loading companies…</p>}

      <div className="jobs">
        {companies.map((c) => (
          <a className="card" key={c.id} href={`/companies/${c.slug}`}>
            <div className="row">
              {c.industry && <span className="pill">{c.industry}</span>}
              {c.verification_status === "verified" && <span className="verified">Verified</span>}
            </div>
            <h2>{c.name}</h2>
            {c.location && <p className="muted">{c.location}</p>}
            {c.description && <p className="muted">{c.description.slice(0, 140)}</p>}
          </a>
        ))}
        {!loading && !companies.length && <p className="empty">No companies found.</p>}
      </div>
    </main>
  );
}
