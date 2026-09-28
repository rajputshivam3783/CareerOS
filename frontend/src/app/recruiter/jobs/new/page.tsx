"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import JobWizard, { EMPTY_JOB_FORM, JobFormState, toJobPayload } from "@/components/JobWizard";

export default function Page() {
  const router = useRouter();
  const [form, setForm] = useState<JobFormState>(EMPTY_JOB_FORM);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function saveDraft() {
    if (!form.title || !form.organization) {
      setErr("Title and organization are required, even for a draft.");
      return;
    }
    setErr("");
    setBusy(true);
    try {
      const job = await api("/recruiter/jobs", { method: "POST", body: JSON.stringify(toJobPayload(form, true)) });
      router.push(`/recruiter/jobs/${job.id}/edit`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!form.title || !form.organization) {
      setErr("Title and organization are required.");
      return;
    }
    setErr("");
    setBusy(true);
    try {
      await api("/recruiter/jobs", { method: "POST", body: JSON.stringify(toJobPayload(form, false)) });
      router.push("/recruiter/jobs");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container page">
      <span className="eyebrow">Job management</span>
      <div className="pagehead">
        <div>
          <h1>Create a job</h1>
          <p className="muted">
            Walk through each section, then either save it as a draft to finish later or submit it straight for
            verification.
          </p>
        </div>
        <a className="btn secondary" href="/recruiter/jobs">
          Back to jobs
        </a>
      </div>

      <JobWizard
        form={form}
        setForm={setForm}
        onSaveDraft={saveDraft}
        onSubmit={submit}
        submitLabel={busy ? "Submitting…" : "Submit for verification"}
        err={err}
      />
    </main>
  );
}
