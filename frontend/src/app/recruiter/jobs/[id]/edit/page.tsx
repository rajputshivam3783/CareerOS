"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import JobWizard, { EMPTY_JOB_FORM, JobFormState, toJobPayload } from "@/components/JobWizard";

function parseList(raw: string | null | undefined): string[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export default function Page() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [form, setForm] = useState<JobFormState>(EMPTY_JOB_FORM);
  const [job, setJob] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api(`/recruiter/jobs/${id}`)
      .then((j) => {
        setJob(j);
        setForm({
          ...EMPTY_JOB_FORM,
          ...j,
          department: j.department || "",
          category: j.category || "",
          employment_type: j.employment_type || "Full-time",
          responsibilities: j.responsibilities || "",
          requirements: j.requirements || "",
          skills: parseList(j.skills),
          benefits: j.benefits || "",
          salary: j.salary || "",
          stipend: j.stipend || "",
          duration: j.duration || "",
          work_mode: j.work_mode || "Onsite",
          vacancies: j.vacancies != null ? String(j.vacancies) : "",
          experience_required: j.experience_required || "",
          qualification: j.qualification || "",
          deadline: j.deadline || "",
          screening_questions: parseList(j.screening_questions),
          apply_url: j.apply_url || "",
        });
      })
      .catch((e: any) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  async function save(nextDraft: boolean) {
    setErr("");
    setBusy(true);
    try {
      await api(`/recruiter/jobs/${id}`, { method: "PUT", body: JSON.stringify(toJobPayload(form, nextDraft)) });
      router.push("/recruiter/jobs");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <main className="container page">Loading…</main>;
  if (!job) return <main className="container page"><p className="error">{err || "Job not found."}</p></main>;

  return (
    <main className="container page">
      <span className="eyebrow">Job management</span>
      <div className="pagehead">
        <div>
          <h1>Edit job</h1>
          <p className="muted">
            {job.status === "draft"
              ? "Still a draft — nothing here is visible until you submit it for review."
              : "This is currently " + job.status + ". Material edits to a published job send it back for re-verification."}
          </p>
        </div>
        <a className="btn secondary" href="/recruiter/jobs">
          Back to jobs
        </a>
      </div>

      <JobWizard
        form={form}
        setForm={setForm}
        onSaveDraft={() => save(job.status === "draft")}
        onSubmit={() => save(job.status === "draft")}
        submitLabel={busy ? "Saving…" : "Save changes"}
        draftLabel={busy ? "Saving…" : "Save changes"}
        err={err}
      />
    </main>
  );
}
