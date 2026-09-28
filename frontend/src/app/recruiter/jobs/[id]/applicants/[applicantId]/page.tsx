"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

const INTERVIEW_MODES = ["video", "phone", "onsite"];
const INTERVIEW_STATUSES = ["scheduled", "completed", "cancelled", "rescheduled"];

function fmt(dt: string | null | undefined) {
  if (!dt) return "";
  try {
    return new Date(dt).toLocaleString();
  } catch {
    return dt;
  }
}

export default function Page() {
  const { id, applicantId } = useParams<{ id: string; applicantId: string }>();
  const [detail, setDetail] = useState<any>(null);
  const [err, setErr] = useState("");
  const [noteText, setNoteText] = useState("");
  const [savingNote, setSavingNote] = useState(false);

  const [ivRound, setIvRound] = useState("Interview");
  const [ivMode, setIvMode] = useState("video");
  const [ivWhen, setIvWhen] = useState("");
  const [ivLink, setIvLink] = useState("");
  const [savingIv, setSavingIv] = useState(false);

  const [offerTitle, setOfferTitle] = useState("");
  const [offerSalary, setOfferSalary] = useState("");
  const [offerStart, setOfferStart] = useState("");
  const [offerExpiry, setOfferExpiry] = useState("");
  const [savingOffer, setSavingOffer] = useState(false);

  async function load() {
    try {
      const d = await api(`/recruiter/applicants/${applicantId}`);
      setDetail(d);
      if (d.offer) {
        setOfferTitle(d.offer.position_title || "");
        setOfferSalary(d.offer.salary || "");
        setOfferStart(d.offer.start_date || "");
        setOfferExpiry(d.offer.expiry_date || "");
      }
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicantId]);

  async function addNote() {
    if (!noteText.trim()) return;
    setSavingNote(true);
    setErr("");
    try {
      await api(`/recruiter/applicants/${applicantId}/notes`, { method: "POST", body: JSON.stringify({ note: noteText }) });
      setNoteText("");
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSavingNote(false);
    }
  }

  async function scheduleInterview() {
    if (!ivWhen) {
      setErr("Pick a date/time for the interview.");
      return;
    }
    setSavingIv(true);
    setErr("");
    try {
      await api(`/recruiter/applicants/${applicantId}/interviews`, {
        method: "POST",
        body: JSON.stringify({
          round_name: ivRound || "Interview",
          mode: ivMode,
          scheduled_at: new Date(ivWhen).toISOString(),
          location_or_link: ivLink || null,
        }),
      });
      setIvRound("Interview");
      setIvMode("video");
      setIvWhen("");
      setIvLink("");
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSavingIv(false);
    }
  }

  async function setInterviewStatus(interviewId: number, status: string) {
    setErr("");
    try {
      await api(`/recruiter/interviews/${interviewId}`, { method: "PATCH", body: JSON.stringify({ status }) });
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function saveOffer() {
    if (!offerTitle.trim()) {
      setErr("Offer needs a position title.");
      return;
    }
    setSavingOffer(true);
    setErr("");
    try {
      await api(`/recruiter/applicants/${applicantId}/offer`, {
        method: "POST",
        body: JSON.stringify({
          position_title: offerTitle,
          salary: offerSalary || null,
          start_date: offerStart || null,
          expiry_date: offerExpiry || null,
        }),
      });
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSavingOffer(false);
    }
  }

  async function sendOffer() {
    setErr("");
    try {
      await api(`/recruiter/applicants/${applicantId}/offer/send`, { method: "POST" });
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function withdrawOffer() {
    if (!window.confirm("Withdraw this offer?")) return;
    setErr("");
    try {
      await api(`/recruiter/applicants/${applicantId}/offer/withdraw`, { method: "POST" });
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  if (err && !detail) return <main className="container page"><p className="error">{err}</p></main>;
  if (!detail) return <main className="container page">Loading…</main>;

  return (
    <main className="container page">
      <span className="eyebrow">Candidate profile</span>
      <div className="pagehead">
        <div>
          <h1>{detail.candidate_name || "Candidate"}</h1>
          <p className="muted">
            {detail.candidate_email} · Applied for {detail.job_title}
          </p>
        </div>
        <a className="btn secondary" href={`/recruiter/jobs/${id}/pipeline`}>
          Back to pipeline
        </a>
      </div>

      {err && <p className="error">{err}</p>}

      <div className="metrics">
        <div className="metric"><b>{detail.status}</b><span>Status</span></div>
        <div className="metric"><b>{detail.pipeline_stage}</b><span>Pipeline stage</span></div>
        <div className="metric"><b>{detail.interviews.length}</b><span>Interviews scheduled</span></div>
      </div>

      <div className="detailgrid">
        <div>
          <div className="card section">
            <h2>Application</h2>
            {detail.cover_note && <p>{detail.cover_note}</p>}
            {!detail.cover_note && <p className="muted">No cover note submitted.</p>}
            {detail.reject_reason && <p className="muted">Rejection reason: {detail.reject_reason}</p>}
            <p className="muted">Applied on {fmt(detail.created_at)}</p>
          </div>

          <div className="card section">
            <h2>Resume</h2>
            {!detail.resume && <p className="muted">This candidate hasn't uploaded a resume yet.</p>}
            {detail.resume && (
              <>
                <p className="strong">{detail.resume.original_filename}</p>
                <p className="muted">Uploaded {fmt(detail.resume.uploaded_at)}</p>
                {detail.resume.skills.length > 0 && (
                  <div className="tagrow">
                    {detail.resume.skills.map((s: string) => (
                      <span key={s} className="tag">{s}</span>
                    ))}
                  </div>
                )}
                <details style={{ marginTop: 10 }}>
                  <summary className="linkbtn">View extracted resume text</summary>
                  <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{detail.resume.extracted_text}</p>
                </details>
              </>
            )}
          </div>

          <div className="card section">
            <h2>Interviews</h2>
            {detail.interviews.map((iv: any) => (
              <div key={iv.id} className="qitem" style={{ marginBottom: 8 }}>
                <div>
                  <b>{iv.round_name}</b>
                  <p className="muted" style={{ margin: "2px 0" }}>
                    {iv.mode} · {fmt(iv.scheduled_at)} {iv.location_or_link ? `· ${iv.location_or_link}` : ""}
                  </p>
                </div>
                <select className="field" style={{ width: 140 }} value={iv.status} onChange={(e) => setInterviewStatus(iv.id, e.target.value)}>
                  {INTERVIEW_STATUSES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            ))}
            {!detail.interviews.length && <p className="muted">No interviews scheduled yet.</p>}

            <h2 className="section" style={{ fontSize: 16 }}>Schedule an interview</h2>
            <div className="grid2">
              <input className="field" placeholder="Round name" value={ivRound} onChange={(e) => setIvRound(e.target.value)} />
              <select className="field" value={ivMode} onChange={(e) => setIvMode(e.target.value)}>
                {INTERVIEW_MODES.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
              <input className="field" type="datetime-local" value={ivWhen} onChange={(e) => setIvWhen(e.target.value)} />
              <input className="field" placeholder="Meeting link / address" value={ivLink} onChange={(e) => setIvLink(e.target.value)} />
            </div>
            <button className="btn" disabled={savingIv} onClick={scheduleInterview}>
              {savingIv ? "Scheduling…" : "Schedule interview"}
            </button>
          </div>

          <div className="card section">
            <h2>Offer</h2>
            {detail.offer && <p className="pill">{detail.offer.status}</p>}
            <div className="grid2">
              <input className="field" placeholder="Position title" value={offerTitle} onChange={(e) => setOfferTitle(e.target.value)} />
              <input className="field" placeholder="Salary" value={offerSalary} onChange={(e) => setOfferSalary(e.target.value)} />
              <input className="field" type="date" placeholder="Start date" value={offerStart || ""} onChange={(e) => setOfferStart(e.target.value)} />
              <input className="field" type="date" placeholder="Expiry date" value={offerExpiry || ""} onChange={(e) => setOfferExpiry(e.target.value)} />
            </div>
            <div className="actions">
              <button className="btn secondary" disabled={savingOffer || detail.offer?.status && detail.offer.status !== "draft"} onClick={saveOffer}>
                {savingOffer ? "Saving…" : detail.offer ? "Update draft" : "Create draft offer"}
              </button>
              {detail.offer?.status === "draft" && (
                <button className="btn" onClick={sendOffer}>Send offer</button>
              )}
              {detail.offer && ["draft", "sent"].includes(detail.offer.status) && (
                <button className="btn danger secondary" onClick={withdrawOffer}>Withdraw</button>
              )}
            </div>
            {detail.offer?.letter_text && (
              <details style={{ marginTop: 10 }}>
                <summary className="linkbtn">View offer letter text</summary>
                <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{detail.offer.letter_text}</p>
              </details>
            )}
          </div>
        </div>

        <div className="stickycard">
          <div className="card section">
            <h2>Private notes</h2>
            <textarea className="field" rows={3} placeholder="Note visible only to you" value={noteText} onChange={(e) => setNoteText(e.target.value)} />
            <button className="btn secondary" style={{ marginTop: 8 }} disabled={savingNote} onClick={addNote}>
              {savingNote ? "Saving…" : "Add note"}
            </button>
            <div style={{ marginTop: 14 }}>
              {detail.notes.map((n: any) => (
                <div key={n.id} style={{ borderTop: "1px solid var(--line)", padding: "10px 0" }}>
                  <p style={{ margin: 0 }}>{n.note}</p>
                  <p className="muted" style={{ margin: "4px 0 0", fontSize: 12 }}>{fmt(n.created_at)}</p>
                </div>
              ))}
              {!detail.notes.length && <p className="muted">No notes yet.</p>}
            </div>
          </div>

          <div className="card section">
            <h2>Activity timeline</h2>
            {detail.timeline.map((e: any, idx: number) => (
              <div key={idx} style={{ borderTop: "1px solid var(--line)", padding: "8px 0" }}>
                <b style={{ fontSize: 13, textTransform: "capitalize" }}>{e.type.replace(/_/g, " ")}</b>
                <p className="muted" style={{ margin: "2px 0 0", fontSize: 12 }}>{fmt(e.at)}</p>
                {e.detail && <p style={{ margin: "2px 0 0", fontSize: 13 }}>{e.detail}</p>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
