import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Latest Government Jobs — CareerOS Government Portal",
  description: "Newly published government recruitment notifications, sourced only from verified official adapters.",
  alternates: { canonical: "/government/latest-jobs" },
  openGraph: { title: "Latest Government Jobs — CareerOS Government Portal", description: "Newly published government recruitment notifications, sourced only from verified official adapters.", type: "website" },
  twitter: { card: "summary", title: "Latest Government Jobs — CareerOS Government Portal", description: "Newly published government recruitment notifications, sourced only from verified official adapters." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Latest Government Jobs" }]} />
      <GovSectionBrowser
        section="latest-jobs"
        title="Latest Government Jobs"
        description="Newly published government recruitment notifications, sourced only from verified official adapters."
        mode="jobs"
        allowInfiniteScroll={true}
        showAdvancedFilters={true}
      />
    </main>
  );
}
