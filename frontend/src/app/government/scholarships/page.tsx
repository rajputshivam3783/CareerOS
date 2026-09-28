import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Scholarships — CareerOS Government Portal",
  description: "Central, state, minority and merit-based scholarship opportunities.",
  alternates: { canonical: "/government/scholarships" },
  openGraph: { title: "Scholarships — CareerOS Government Portal", description: "Central, state, minority and merit-based scholarship opportunities.", type: "website" },
  twitter: { card: "summary", title: "Scholarships — CareerOS Government Portal", description: "Central, state, minority and merit-based scholarship opportunities." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Scholarships" }]} />
      <GovSectionBrowser
        section="scholarships"
        title="Scholarships"
        description="Central, state, minority and merit-based scholarship opportunities."
        mode="jobs"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
