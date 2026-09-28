import { API } from "@/lib/api";
import { safeJsonLd } from "@/lib/safe";
import JobDetailClient from "./JobDetailClient";

async function loadJob(id: string) {
  try {
    const r = await fetch(`${API}/jobs/${id}`, { next: { revalidate: 60 } });
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function loadTimeline(id: string) {
  try {
    const r = await fetch(`${API}/jobs/${id}/timeline`, { next: { revalidate: 60 } });
    if (!r.ok) return [];
    const x = await r.json();
    return x?.updates || [];
  } catch {
    return [];
  }
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const job = await loadJob(id);
  if (!job) return { title: "Opportunity — CareerOS" };
  const title = `${job.title} — ${job.organization} | CareerOS`;
  const description = (job.description || `${job.title} recruitment by ${job.organization}.`).slice(0, 200);
  return {
    title,
    description,
    alternates: { canonical: `/jobs/${id}` },
    openGraph: { title, description, type: "article" },
    twitter: { card: "summary", title, description },
  };
}

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [job, timeline] = await Promise.all([loadJob(id), loadTimeline(id)]);

  const jsonLd = job ? {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: job.title,
    description: job.description || job.title,
    datePosted: job.created_at || undefined,
    validThrough: job.deadline || undefined,
    hiringOrganization: { "@type": "Organization", name: job.organization },
    jobLocation: job.location ? { "@type": "Place", address: job.location } : undefined,
    employmentType: job.employment_type || undefined,
    identifier: job.ad_number ? { "@type": "PropertyValue", name: "Advertisement Number", value: job.ad_number } : undefined,
  } : null;

  return (
    <>
      {jsonLd && <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(jsonLd) }} />}
      <JobDetailClient id={Number(id)} initialJob={job} initialTimeline={timeline} />
    </>
  );
}
