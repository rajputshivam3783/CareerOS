import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Admissions — CareerOS Government Portal",
  description: "University, NTA and counselling-based admission notifications.",
  alternates: { canonical: "/government/admissions" },
  openGraph: { title: "Admissions — CareerOS Government Portal", description: "University, NTA and counselling-based admission notifications.", type: "website" },
  twitter: { card: "summary", title: "Admissions — CareerOS Government Portal", description: "University, NTA and counselling-based admission notifications." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Admissions" }]} />
      <GovSectionBrowser
        section="admissions"
        title="Admissions"
        description="University, NTA and counselling-based admission notifications."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
