import { Suspense } from "react";
import ApplicationsClient from "./ApplicationsClient";

// V22.2 SMART APPLICATION DASHBOARD. Thin wrapper so useSearchParams
// (used in ApplicationsClient for URL-addressable filter/view state)
// doesn't force the whole route out of static optimization — same
// page/Client split already used by discover/page.tsx elsewhere in
// this app.
export const metadata = {
  title: "Your Applications — CareerOS",
  description: "Track every job application from saved to offer, with a Kanban board and list view.",
};

export default function ApplicationsPage() {
  return (
    <Suspense fallback={<main className="page"><div className="container"><p className="loading">Loading…</p></div></main>}>
      <ApplicationsClient />
    </Suspense>
  );
}
