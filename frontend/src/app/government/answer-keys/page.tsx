import GovSectionBrowser from "@/components/GovSectionBrowser";
import Breadcrumbs from "@/components/Breadcrumbs";

export const metadata = {
  title: "Answer Keys — CareerOS Government Portal",
  description: "Provisional and final answer keys, including objection window details where published.",
  alternates: { canonical: "/government/answer-keys" },
  openGraph: { title: "Answer Keys — CareerOS Government Portal", description: "Provisional and final answer keys, including objection window details where published.", type: "website" },
  twitter: { card: "summary", title: "Answer Keys — CareerOS Government Portal", description: "Provisional and final answer keys, including objection window details where published." },
};

export default function Page() {
  return (
    <main className="container page">
      <Breadcrumbs items={[{ label: "Government Portal", href: "/government" }, { label: "Answer Keys" }]} />
      <GovSectionBrowser
        section="answer-keys"
        title="Answer Keys"
        description="Provisional and final answer keys, including objection window details where published."
        mode="updates"
        allowInfiniteScroll={false}
        showAdvancedFilters={false}
      />
    </main>
  );
}
