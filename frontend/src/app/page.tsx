import Link from "next/link";

export default function Page() {
  return (
    <main>
      <section className="hero container">
        <span className="eyebrow">Built for India&rsquo;s job seekers</span>
        <h1>Find the right opportunity. Prepare well. Apply with confidence.</h1>
        <p>
          One workspace for government exams, private jobs, internships and apprenticeships — with
          verified sources, eligibility guidance, resume matching and application tracking.
        </p>
        <div className="actions">
          <Link className="btn" href="/jobs">
            Search opportunities
          </Link>
          <Link className="btn secondary" href="/government">
            Government hub
          </Link>
          <Link className="btn secondary" href="/login">
            Candidate account
          </Link>
          <Link className="btn secondary" href="/recruiter-login">
            Employer portal
          </Link>
        </div>
        <div className="trustbar">
          <span>✓ Human-reviewed listings</span>
          <span>✓ Official-source links</span>
          <span>✓ Recruiter verification</span>
          <span>✓ No pay-to-apply flow</span>
        </div>
      </section>

      <section className="container grid3">
        <div className="card feature">
          <span className="featureicon">Government</span>
          <b>Government jobs &amp; exams</b>
          <p>Reviewed UPSC and other official-source opportunities, with lifecycle updates as they change.</p>
        </div>
        <div className="card feature">
          <span className="featureicon">Private sector</span>
          <b>Private careers</b>
          <p>Verified recruiters publish jobs, internships and apprenticeships only after admin review.</p>
        </div>
        <div className="card feature">
          <span className="featureicon">AI-assisted</span>
          <b>Career intelligence</b>
          <p>Compare your profile and resume against roles, spot skill gaps and get an action plan.</p>
        </div>
      </section>

      <section className="container platform">
        <span className="eyebrow">From discovery to offer</span>
        <h2>A complete application operating system</h2>
        <div className="grid3">
          <div>
            <b>Discover</b>
            <p>Search, filters, verified sources and saved opportunities.</p>
          </div>
          <div>
            <b>Prepare</b>
            <p>Eligibility checks, resume matching, exam resources and skill gaps.</p>
          </div>
          <div>
            <b>Execute</b>
            <p>Applications, deadlines, alerts, notifications and recruiter pipeline.</p>
          </div>
        </div>
      </section>
    </main>
  );
}
