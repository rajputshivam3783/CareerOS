import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Merit Lists — CareerOS Government Portal",
  description: "Merit lists published by recruiting and admitting organizations.",
  alternates: { canonical: "/government/merit-lists" },
  openGraph: { title: "Merit Lists — CareerOS Government Portal", description: "Merit lists published by recruiting and admitting organizations.", type: "website" },
  twitter: { card: "summary", title: "Merit Lists — CareerOS Government Portal", description: "Merit lists published by recruiting and admitting organizations." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Merit Lists" }]} />
      <GovSectionBrowser
        section="merit-lists"
        title="Merit Lists"
        description="Merit lists published by recruiting and admitting organizations."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
