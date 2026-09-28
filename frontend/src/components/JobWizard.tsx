"use client";

import { useState } from "react";

const PRIVATE_JOB_TYPES = ["Private", "Internship", "Apprenticeship"];
const EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Contract", "Internship", "Apprenticeship", "Freelance"];
const WORK_MODES = ["Onsite", "Remote", "Hybrid"];

const STEPS = [
  "Basic Details",
  "Description",
  "Responsibilities & Requirements",
  "Skills & Benefits",
  "Compensation",
  "Location & Work Mode",
  "Experience & Education",
  "Deadline & Screening",
];

export type JobFormState = {
  title: string;
  organization: string;
  department: string;
  job_type: string;
  category: string;
  employment_type: string;
  description: string;
  responsibilities: string;
  requirements: string;
  skills: string[];
  benefits: string;
  salary: string;
  stipend: string;
  duration: string;
  location: string;
  work_mode: string;
  vacancies: string;
  experience_required: string;
  qualification: string;
  deadline: string;
  screening_questions: string[];
  apply_url: string;
};

export const EMPTY_JOB_FORM: JobFormState = {
  title: "",
  organization: "",
  department: "",
  job_type: "Private",
  category: "",
  employment_type: "Full-time",
  description: "",
  responsibilities: "",
  requirements: "",
  skills: [],
  benefits: "",
  salary: "",
  stipend: "",
  duration: "",
  location: "India",
  work_mode: "Onsite",
  vacancies: "",
  experience_required: "",
  qualification: "",
  deadline: "",
  screening_questions: [],
  apply_url: "",
};

/** Turns a wizard form into the exact body app.api.recruiter's
 * RecruiterJobIn expects (POST /recruiter/jobs, PUT /recruiter/jobs/{id}). */
export function toJobPayload(form: JobFormState, saveAsDraft: boolean) {
  return {
    title: form.title,
    organization: form.organization,
    department: form.department || null,
    job_type: form.job_type,
    category: form.category || null,
    employment_type: form.employment_type || null,
    work_mode: form.work_mode || null,
    industry: null,
    experience_required: form.experience_required || null,
    location: form.location || "India",
    vacancies: form.vacancies ? Number(form.vacancies) : null,
    qualification: form.qualification || "See job description",
    salary: form.salary || null,
    stipend: form.stipend || null,
    duration: form.duration || null,
    deadline: form.deadline || null,
    description: form.description || "See job description",
    apply_url: form.apply_url || null,
    responsibilities: form.responsibilities || null,
    requirements: form.requirements || null,
    skills: form.skills.length ? form.skills : null,
    benefits: form.benefits || null,
    screening_questions: form.screening_questions.length ? form.screening_questions : null,
    save_as_draft: saveAsDraft,
  };
}

function TagEditor({
  label,
  placeholder,
  values,
  onChange,
}: {
  label: string;
  placeholder: string;
  values: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  function add() {
    const v = draft.trim();
    if (!v || values.includes(v)) return;
    onChange([...values, v]);
    setDraft("");
  }
  return (
    <div>
      <p className="field-label">{label}</p>
      {values.length > 0 && (
        <div className="tagrow">
          {values.map((v) => (
            <span className="tag" key={v}>
              {v}
              <button type="button" onClick={() => onChange(values.filter((x) => x !== v))}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="tagadd">
        <input
          className="field"
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="btn secondary" onClick={add}>
          Add
        </button>
      </div>
    </div>
  );
}

export default function JobWizard({
  form,
  setForm,
  onSaveDraft,
  onSubmit,
  submitLabel,
  draftLabel = "Save as draft",
  err,
}: {
  form: JobFormState;
  setForm: (next: JobFormState) => void;
  onSaveDraft: () => void;
  onSubmit: () => void;
  submitLabel: string;
  draftLabel?: string;
  err?: string;
}) {
  const [step, setStep] = useState(0);
  const last = step === STEPS.length - 1;

  function set<K extends keyof JobFormState>(key: K, value: JobFormState[K]) {
    setForm({ ...form, [key]: value });
  }

  return (
    <div className="card form">
      <div className="steps">
        {STEPS.map((label, i) => (
          <button
            type="button"
            key={label}
            className={`step ${i === step ? "step-active" : i < step ? "step-done" : ""}`}
            onClick={() => setStep(i)}
          >
            {i + 1}. {label}
          </button>
        ))}
      </div>

      {err && <p className="error">{err}</p>}

      {step === 0 && (
        <div className="grid2">
          <input className="field" placeholder="Job title" value={form.title} onChange={(e) => set("title", e.target.value)} />
          <input
            className="field"
            placeholder="Company / organization"
            value={form.organization}
            onChange={(e) => set("organization", e.target.value)}
          />
          <input className="field" placeholder="Department (optional)" value={form.department} onChange={(e) => set("department", e.target.value)} />
          <select className="field" value={form.job_type} onChange={(e) => set("job_type", e.target.value)}>
            {PRIVATE_JOB_TYPES.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
          <input className="field" placeholder="Category (optional)" value={form.category} onChange={(e) => set("category", e.target.value)} />
          <select className="field" value={form.employment_type} onChange={(e) => set("employment_type", e.target.value)}>
            {EMPLOYMENT_TYPES.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </div>
      )}

      {step === 1 && (
        <textarea
          className="field"
          rows={8}
          placeholder="Job description — what the role is and why it matters"
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
        />
      )}

      {step === 2 && (
        <div style={{ display: "grid", gap: 16 }}>
          <textarea
            className="field"
            rows={6}
            placeholder="Key responsibilities (one per line)"
            value={form.responsibilities}
            onChange={(e) => set("responsibilities", e.target.value)}
          />
          <textarea
            className="field"
            rows={6}
            placeholder="Requirements / must-haves (one per line)"
            value={form.requirements}
            onChange={(e) => set("requirements", e.target.value)}
          />
        </div>
      )}

      {step === 3 && (
        <div style={{ display: "grid", gap: 16 }}>
          <TagEditor
            label="Skills"
            placeholder="e.g. Python — press Enter to add"
            values={form.skills}
            onChange={(next) => set("skills", next)}
          />
          <textarea
            className="field"
            rows={5}
            placeholder="Benefits & perks"
            value={form.benefits}
            onChange={(e) => set("benefits", e.target.value)}
          />
        </div>
      )}

      {step === 4 && (
        <div className="grid2">
          <input className="field" placeholder="Salary (e.g. ₹12–18 LPA)" value={form.salary} onChange={(e) => set("salary", e.target.value)} />
          <input className="field" placeholder="Stipend (if internship)" value={form.stipend} onChange={(e) => set("stipend", e.target.value)} />
          <input className="field" placeholder="Duration (e.g. 6 months)" value={form.duration} onChange={(e) => set("duration", e.target.value)} />
        </div>
      )}

      {step === 5 && (
        <div className="grid2">
          <input className="field" placeholder="Location" value={form.location} onChange={(e) => set("location", e.target.value)} />
          <select className="field" value={form.work_mode} onChange={(e) => set("work_mode", e.target.value)}>
            {WORK_MODES.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
          <input
            className="field"
            placeholder="Vacancies"
            type="number"
            value={form.vacancies}
            onChange={(e) => set("vacancies", e.target.value)}
          />
        </div>
      )}

      {step === 6 && (
        <div className="grid2">
          <input
            className="field"
            placeholder="Experience required (e.g. 2-4 years)"
            value={form.experience_required}
            onChange={(e) => set("experience_required", e.target.value)}
          />
          <input
            className="field"
            placeholder="Education / qualification"
            value={form.qualification}
            onChange={(e) => set("qualification", e.target.value)}
          />
        </div>
      )}

      {step === 7 && (
        <div style={{ display: "grid", gap: 16 }}>
          <div className="grid2">
            <div>
              <p className="field-label">Application deadline</p>
              <input className="field" type="date" value={form.deadline} onChange={(e) => set("deadline", e.target.value)} />
            </div>
            <input
              className="field"
              placeholder="External apply URL (optional)"
              value={form.apply_url}
              onChange={(e) => set("apply_url", e.target.value)}
            />
          </div>
          <TagEditor
            label="Screening questions"
            placeholder="e.g. Are you authorized to work in India? — press Enter to add"
            values={form.screening_questions}
            onChange={(next) => set("screening_questions", next)}
          />
        </div>
      )}

      <div className="wizardnav">
        <div className="actions">
          <button type="button" className="btn secondary" disabled={step === 0} onClick={() => setStep(step - 1)}>
            Back
          </button>
          {!last && (
            <button type="button" className="btn secondary" onClick={() => setStep(step + 1)}>
              Next
            </button>
          )}
        </div>
        <div className="actions">
          <button type="button" className="btn secondary" onClick={onSaveDraft}>
            {draftLabel}
          </button>
          {last && (
            <button type="button" className="btn" onClick={onSubmit}>
              {submitLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
