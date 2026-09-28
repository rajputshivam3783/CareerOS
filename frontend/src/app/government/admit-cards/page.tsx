import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Admit Cards — CareerOS Government Portal",
  description: "Upcoming and released admit cards / hall tickets for government exams.",
  alternates: { canonical: "/government/admit-cards" },
  openGraph: { title: "Admit Cards — CareerOS Government Portal", description: "Upcoming and released admit cards / hall tickets for government exams.", type: "website" },
  twitter: { card: "summary", title: "Admit Cards — CareerOS Government Portal", description: "Upcoming and released admit cards / hall tickets for government exams." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Admit Cards" }]} />
      <GovSectionBrowser
        section="admit-cards"
        title="Admit Cards"
        description="Upcoming and released admit cards / hall tickets for government exams."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
