import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Archive — CareerOS Government Portal",
  description: "Closed and archived government recruitments, kept for reference.",
  alternates: { canonical: "/government/archive" },
  openGraph: { title: "Archive — CareerOS Government Portal", description: "Closed and archived government recruitments, kept for reference.", type: "website" },
  twitter: { card: "summary", title: "Archive — CareerOS Government Portal", description: "Closed and archived government recruitments, kept for reference." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Archive" }]} />
      <GovSectionBrowser
        section="archive"
        title="Archive"
        description="Closed and archived government recruitments, kept for reference."
        mode="jobs"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
