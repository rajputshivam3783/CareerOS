import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Cancelled Recruitments — CareerOS Government Portal",
  description: "Recruitments that have been officially cancelled or withdrawn.",
  alternates: { canonical: "/government/cancelled-recruitments" },
  openGraph: { title: "Cancelled Recruitments — CareerOS Government Portal", description: "Recruitments that have been officially cancelled or withdrawn.", type: "website" },
  twitter: { card: "summary", title: "Cancelled Recruitments — CareerOS Government Portal", description: "Recruitments that have been officially cancelled or withdrawn." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Cancelled Recruitments" }]} />
      <GovSectionBrowser
        section="cancelled-recruitments"
        title="Cancelled Recruitments"
        description="Recruitments that have been officially cancelled or withdrawn."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
