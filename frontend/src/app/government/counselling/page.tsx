import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Counselling — CareerOS Government Portal",
  description: "Counselling schedules and seat allocation notices.",
  alternates: { canonical: "/government/counselling" },
  openGraph: { title: "Counselling — CareerOS Government Portal", description: "Counselling schedules and seat allocation notices.", type: "website" },
  twitter: { card: "summary", title: "Counselling — CareerOS Government Portal", description: "Counselling schedules and seat allocation notices." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Counselling" }]} />
      <GovSectionBrowser
        section="counselling"
        title="Counselling"
        description="Counselling schedules and seat allocation notices."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
