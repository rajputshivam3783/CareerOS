import "./globals.css";
import Nav from "@/components/Nav";

export const metadata = {
  title: "CareerOS — Jobs, Exams & Career Intelligence",
  description:
    "Verified government and private jobs, career matching, applications and recruiter hiring workspace",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Nav />
        <div id="main">{children}</div>
        <footer>
          <div className="container footergrid">
            <div>
              <b>CareerOS</b>
              <p>Verified opportunities. Smarter career decisions.</p>
            </div>
            <div>
              <b>For candidates</b>
              <p>Jobs · Resume match · Career AI · Application tracker</p>
            </div>
            <div>
              <b>Trust &amp; safety</b>
              <p>Always verify deadlines and eligibility on the official source before applying.</p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
