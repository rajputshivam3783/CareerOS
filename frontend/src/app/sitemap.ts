import { API } from "@/lib/api";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://careeros.example.com";

const STATIC_SECTIONS = [
  "", "discover", "jobs", "companies", "government", "government/search", "government/latest-jobs",
  "government/results", "government/admit-cards", "government/answer-keys", "government/syllabus",
  "government/admissions", "government/scholarships", "government/counselling", "government/cutoffs",
  "government/merit-lists", "government/document-verification", "government/medical-examination",
  "government/final-selection", "government/joining", "government/cancelled-recruitments", "government/archive",
];

export default async function sitemap() {
  const staticEntries = STATIC_SECTIONS.map(path => ({
    url: `${SITE_URL}/${path}`,
    lastModified: new Date(),
    changeFrequency: path === "" ? "daily" : "hourly",
    priority: path === "" ? 1 : 0.8,
  }));

  let jobEntries: any[] = [];
  try {
    // Most recently published jobs only — a sitemap doesn't need every
    // historical record, and this keeps the fetch bounded.
    const r = await fetch(`${API}/jobs?limit=500&job_type=Government`, { next: { revalidate: 3600 } });
    if (r.ok) {
      const jobs = await r.json();
      jobEntries = jobs.map((j: any) => ({
        url: `${SITE_URL}/jobs/${j.id}`,
        lastModified: new Date(),
        changeFrequency: "daily",
        priority: 0.6,
      }));
    }
  } catch {
    // Sitemap generation shouldn't fail the build if the API is briefly unreachable.
  }

  return [...staticEntries, ...jobEntries];
}
