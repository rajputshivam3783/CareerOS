import { Suspense } from "react";
import CandidatesClient from "./CandidatesClient";

// V24.2 — thin wrapper so useSearchParams (job_id deep link from
// /recruiter/jobs) doesn't force the route out of static optimization,
// same split already used by /applications and /discover.
export const metadata = {
  title: "Find candidates — CareerOS Recruiter Workspace",
  description: "Search and filter candidates, or find the best matches for one of your jobs.",
};

export default function Page() {
  return (
    <Suspense fallback={<main className="container page"><p className="loading">Loading…</p></main>}>
      <CandidatesClient />
    </Suspense>
  );
}
