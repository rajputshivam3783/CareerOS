import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Medical Examination — CareerOS Government Portal",
  description: "Medical examination schedules for shortlisted candidates.",
  alternates: { canonical: "/government/medical-examination" },
  openGraph: { title: "Medical Examination — CareerOS Government Portal", description: "Medical examination schedules for shortlisted candidates.", type: "website" },
  twitter: { card: "summary", title: "Medical Examination — CareerOS Government Portal", description: "Medical examination schedules for shortlisted candidates." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Medical Examination" }]} />
      <GovSectionBrowser
        section="medical-examination"
        title="Medical Examination"
        description="Medical examination schedules for shortlisted candidates."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
