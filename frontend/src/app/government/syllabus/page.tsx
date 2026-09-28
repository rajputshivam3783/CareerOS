import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Syllabus — CareerOS Government Portal",
  description: "Exam-wise and organization-wise syllabus documents.",
  alternates: { canonical: "/government/syllabus" },
  openGraph: { title: "Syllabus — CareerOS Government Portal", description: "Exam-wise and organization-wise syllabus documents.", type: "website" },
  twitter: { card: "summary", title: "Syllabus — CareerOS Government Portal", description: "Exam-wise and organization-wise syllabus documents." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Syllabus" }]} />
      <GovSectionBrowser
        section="syllabus"
        title="Syllabus"
        description="Exam-wise and organization-wise syllabus documents."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
