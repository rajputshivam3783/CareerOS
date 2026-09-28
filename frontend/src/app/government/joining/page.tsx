import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Joining — CareerOS Government Portal",
  description: "Joining instructions and appointment letters.",
  alternates: { canonical: "/government/joining" },
  openGraph: { title: "Joining — CareerOS Government Portal", description: "Joining instructions and appointment letters.", type: "website" },
  twitter: { card: "summary", title: "Joining — CareerOS Government Portal", description: "Joining instructions and appointment letters." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Joining" }]} />
      <GovSectionBrowser
        section="joining"
        title="Joining"
        description="Joining instructions and appointment letters."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
