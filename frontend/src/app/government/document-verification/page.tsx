import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Document Verification — CareerOS Government Portal",
  description: "Document verification schedules and venue notices.",
  alternates: { canonical: "/government/document-verification" },
  openGraph: { title: "Document Verification — CareerOS Government Portal", description: "Document verification schedules and venue notices.", type: "website" },
  twitter: { card: "summary", title: "Document Verification — CareerOS Government Portal", description: "Document verification schedules and venue notices." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Document Verification" }]} />
      <GovSectionBrowser
        section="document-verification"
        title="Document Verification"
        description="Document verification schedules and venue notices."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
