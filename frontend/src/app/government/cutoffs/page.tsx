import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Cutoffs — CareerOS Government Portal",
  description: "Category-wise and post-wise cutoff marks as released by the organization.",
  alternates: { canonical: "/government/cutoffs" },
  openGraph: { title: "Cutoffs — CareerOS Government Portal", description: "Category-wise and post-wise cutoff marks as released by the organization.", type: "website" },
  twitter: { card: "summary", title: "Cutoffs — CareerOS Government Portal", description: "Category-wise and post-wise cutoff marks as released by the organization." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Cutoffs" }]} />
      <GovSectionBrowser
        section="cutoffs"
        title="Cutoffs"
        description="Category-wise and post-wise cutoff marks as released by the organization."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
