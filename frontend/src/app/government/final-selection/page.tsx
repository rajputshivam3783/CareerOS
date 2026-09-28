import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Final Selection — CareerOS Government Portal",
  description: "Final selection lists published at the end of a recruitment cycle.",
  alternates: { canonical: "/government/final-selection" },
  openGraph: { title: "Final Selection — CareerOS Government Portal", description: "Final selection lists published at the end of a recruitment cycle.", type: "website" },
  twitter: { card: "summary", title: "Final Selection — CareerOS Government Portal", description: "Final selection lists published at the end of a recruitment cycle." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Final Selection" }]} />
      <GovSectionBrowser
        section="final-selection"
        title="Final Selection"
        description="Final selection lists published at the end of a recruitment cycle."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
