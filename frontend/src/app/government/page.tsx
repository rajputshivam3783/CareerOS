import Link from "next/link";
import { API } from "@/lib/api";
import GovHomeClient from "./GovHomeClient";

export const metadata = {
  title: "Government Portal — CareerOS",
  description: "Government recruitment, results, admit cards, answer keys, admissions and scholarships — sourced only from verified official adapters, never hardcoded.",
  alternates: { canonical: "/government" },
  openGraph: {
    title: "Government Portal — CareerOS",
    description: "Government recruitment, results, admit cards, answer keys, admissions and scholarships — sourced only from verified official adapters.",
    type: "website",
  },
  twitter: { card: "summary_large_image", title: "Government Portal — CareerOS" },
};

const SECTIONS: { slug: string; label: string; countKey: string }[] = [
  { slug: "latest-jobs", label: "Latest Jobs", countKey: "latest_jobs" },
  { slug: "results", label: "Results", countKey: "results" },
  { slug: "admit-cards", label: "Admit Cards", countKey: "admit_cards" },
  { slug: "answer-keys", label: "Answer Keys", countKey: "answer_keys" },
  { slug: "syllabus", label: "Syllabus", countKey: "syllabus" },
  { slug: "admissions", label: "Admissions", countKey: "admissions" },
  { slug: "scholarships", label: "Scholarships", countKey: "scholarships" },
  { slug: "counselling", label: "Counselling", countKey: "counselling" },
  { slug: "cutoffs", label: "Cutoffs", countKey: "cutoffs" },
  { slug: "merit-lists", label: "Merit Lists", countKey: "merit_lists" },
  { slug: "document-verification", label: "Document Verification", countKey: "document_verification" },
  { slug: "medical-examination", label: "Medical Examination", countKey: "medical_examination" },
  { slug: "final-selection", label: "Final Selection", countKey: "final_selection" },
  { slug: "joining", label: "Joining", countKey: "joining" },
  { slug: "cancelled-recruitments", label: "Cancelled Recruitments", countKey: "cancelled_recruitments" },
  { slug: "archive", label: "Archive", countKey: "archive" },
];

async function loadHome() {
  try {
    const r = await fetch(`${API}/government/home`, { next: { revalidate: 120 } });
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

export default async function Page() {
  const home = await loadHome();
  const counts = home?.counts || {};

  return (
    <main className="container page">
      <section className="gov-hero">
        <span className="eyebrow">CareerOS · government portal</span>
        <h1>Every government recruitment update, in one place.</h1>
        <p className="muted">
          Jobs, results, admit cards, answer keys, admissions and scholarships — pulled only from
          verified official sources through CareerOS&apos;s adapter framework. Nothing here is hand-entered.
        </p>
        <div className="actions">
          <Link className="btn" href="/government/latest-jobs">Browse latest jobs</Link>
          <Link className="btn secondary" href="/government/search">Advanced search</Link>
          <Link className="btn secondary" href="/career-copilot">Ask the Career Copilot about eligibility</Link>
        </div>
      </section>

      <h2>Browse by section</h2>
      <div className="sectiongrid">
        {SECTIONS.map(s => (
          <Link key={s.slug} href={`/government/${s.slug}`} className="card">
            <b>{s.label}</b>
            <p className="muted">{counts[s.countKey] ?? 0} listed</p>
          </Link>
        ))}
      </div>

      <GovHomeClient initialLatest={home?.latest_jobs || []} initialClosingSoon={home?.closing_soon || []} />
    </main>
  );
}
