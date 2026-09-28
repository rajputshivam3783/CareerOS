// V25.6 — Frontend output-safety helpers.
//
// Two concrete problems these exist to close (see
// docs/V25_FINAL_SECURITY_AND_COMPLIANCE_AUDIT.md, findings F-01/F-02):
//
//  1. `<script type="application/ld+json">` blocks were rendered with
//     `JSON.stringify(...)` inside dangerouslySetInnerHTML. JSON.stringify does
//     NOT escape "<", so a job title containing "</script><script>..." closes the
//     block and runs attacker-controlled script on a public page.
//  2. Recruiter/partner/ingestion-supplied URLs (apply_url, official_url, ...) were
//     placed straight into href attributes, allowing `javascript:` / `data:` URLs.
//
// Both helpers are pure functions with no dependencies.

/** Serialize a value for embedding inside a <script> element without allowing the
 *  content to terminate the element or open an HTML comment. Escapes < > & and the
 *  U+2028/U+2029 line separators as JSON unicode escapes (still valid JSON). */
export function safeJsonLd(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

/** Returns the URL only if it is an absolute http(s) URL; otherwise undefined so the
 *  attribute is omitted. Relative URLs are rejected on purpose: every caller passes
 *  an external link supplied by a third party. Never throws. */
export function safeHref(url: string | null | undefined): string | undefined {
  if (typeof url !== "string") return undefined;
  const trimmed = url.trim();
  if (!trimmed || trimmed.length > 2048) return undefined;
  // Reject control characters (browsers strip tabs/newlines inside schemes, which is
  // the classic "java\nscript:" bypass).
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(trimmed)) return undefined;
  try {
    const parsed = new URL(trimmed);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : undefined;
  } catch {
    return undefined;
  }
}
