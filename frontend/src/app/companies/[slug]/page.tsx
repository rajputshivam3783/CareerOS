"use client";
import { safeHref } from "@/lib/safe";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { API } from "@/lib/api";

export default function Page() {
  const params = useParams();
  const slug = String(params.slug);
  const [company, setCompany] = useState<any>(null);
  const [branches, setBranches] = useState<any[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    fetch(`${API}/companies/${slug}`)
      .then(async (r) => {
        if (!r.ok) throw new Error("Company not found");
        return r.json();
      })
      .then((data) => {
        setCompany(data.company);
        setBranches(data.branches || []);
      })
      .catch((e) => setErr(e.message));
  }, [slug]);

  if (err) return <main className="container page"><p className="error">{err}</p></main>;
  if (!company) return <main className="container page"><p>Loading…</p></main>;

  const headquarters = branches.find((b) => b.is_headquarters);
  const otherBranches = branches.filter((b) => !b.is_headquarters);

  return (
    <main className="container page">
      <div className="detailgrid">
        <article>
          <span className="eyebrow">Company</span>
          <div className="row">
            {company.industry && <span className="pill">{company.industry}</span>}
            {company.verification_status === "verified" && <span className="verified">Verified</span>}
          </div>
          <h1>{company.name}</h1>
          {company.location && <p className="strong">{company.location}</p>}

          <div className="jobmeta">
            <span>
              Company size
              <b>{company.company_size || "Not specified"}</b>
            </span>
            <span>
              Founded
              <b>{company.founded_year || "Not specified"}</b>
            </span>
          </div>

          {company.description && (
            <section className="card section">
              <h2>About {company.name}</h2>
              <p>{company.description}</p>
            </section>
          )}

          {branches.length > 0 && (
            <section className="card section">
              <h2>Locations</h2>
              {headquarters && (
                <div>
                  <span className="pill">HQ</span>
                  <b> {headquarters.branch_name}</b>
                  <p className="muted">{headquarters.location}</p>
                </div>
              )}
              {otherBranches.map((b) => (
                <div key={b.id} style={{ marginTop: 12 }}>
                  <b>{b.branch_name}</b>
                  <p className="muted">{b.location}</p>
                </div>
              ))}
            </section>
          )}
        </article>

        <aside className="card stickycard">
          <h2>Links</h2>
          <div className="form">
            {company.website && (
              <a className="btn secondary" target="_blank" rel="noreferrer" href={safeHref(company.website)}>
                Company website
              </a>
            )}
            {company.linkedin_url && (
              <a className="btn secondary" target="_blank" rel="noreferrer" href={safeHref(company.linkedin_url)}>
                LinkedIn
              </a>
            )}
            {company.twitter_url && (
              <a className="btn secondary" target="_blank" rel="noreferrer" href={safeHref(company.twitter_url)}>
                Twitter / X
              </a>
            )}
            {company.facebook_url && (
              <a className="btn secondary" target="_blank" rel="noreferrer" href={safeHref(company.facebook_url)}>
                Facebook
              </a>
            )}
            {company.instagram_url && (
              <a className="btn secondary" target="_blank" rel="noreferrer" href={safeHref(company.instagram_url)}>
                Instagram
              </a>
            )}
          </div>
        </aside>
      </div>
    </main>
  );
}
