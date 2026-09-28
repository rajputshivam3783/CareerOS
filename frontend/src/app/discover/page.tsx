import { Suspense } from "react";
import DiscoverClient from "./DiscoverClient";

// V21.2 UNIFIED JOB DISCOVERY. Thin wrapper so useSearchParams (used
// in DiscoverClient for URL-addressable SEARCH STATE) doesn't force
// the whole route out of static optimization — same page/Client split
// already used by jobs/[id]/page.tsx + JobDetailClient.tsx elsewhere
// in this app.
export const metadata = {
  title: "Discover Opportunities — CareerOS",
  description: "Search private jobs, government recruitments, internships, and apprenticeships in one place.",
  alternates: { canonical: "/discover" },
};

export default function DiscoverPage() {
  return (
    <Suspense fallback={<main className="page"><div className="container"><p className="loading">Loading…</p></div></main>}>
      <DiscoverClient />
    </Suspense>
  );
}
