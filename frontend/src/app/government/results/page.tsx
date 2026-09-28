import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Latest Results — CareerOS Government Portal",
  description: "Government exam and recruitment results as they are published by the issuing organization.",
  alternates: { canonical: "/government/results" },
  openGraph: { title: "Latest Results — CareerOS Government Portal", description: "Government exam and recruitment results as they are published by the issuing organization.", type: "website" },
  twitter: { card: "summary", title: "Latest Results — CareerOS Government Portal", description: "Government exam and recruitment results as they are published by the issuing organization." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Latest Results" }]} />
      <GovSectionBrowser
        section="results"
        title="Latest Results"
        description="Government exam and recruitment results as they are published by the issuing organization."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
