"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, formatApiError } from "@/lib/api";
import ReportView from "../../ReportView";

export default function InterviewReportPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const [report, setReport] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api(`/interview/sessions/${sessionId}/report`)
      .then(setReport)
      .catch((e) => setErr(formatApiError(e.message, "Report not available for this interview")));
  }, [sessionId]);

  if (err) return <main className="container page"><p className="error">{err}</p></main>;
  if (!report) return <main className="container page"><p className="muted">Loading…</p></main>;

  return (
    <main className="container page">
      <ReportView report={report} sessionId={sessionId} />
    </main>
  );
}
