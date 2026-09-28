// V25.6 — dependency-free test for src/lib/safe.ts. Run: npm run test:security (Node >= 22.6)
import { safeHref, safeJsonLd } from "../src/lib/safe.ts";
import assert from "node:assert/strict";
const evil = { title: "</script><script>alert(1)</script>", d: "<!-- x --> & \u2028" };
const out = safeJsonLd(evil);
assert(!out.includes("<") && !out.includes(">") && !out.includes("&"), out);
assert.deepEqual(JSON.parse(out), evil);            // still valid JSON, round-trips exactly
assert.equal(safeHref("https://example.com/a?b=1"), "https://example.com/a?b=1");
assert.equal(safeHref("http://example.com"), "http://example.com/");
for (const bad of ["javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)", "java\nscript:alert(1)", "data:text/html,<script>", "vbscript:x", "//evil.com", "/relative", "", null, undefined, "https://a.com/\u0000"]) {
  assert.equal(safeHref(bad), undefined, String(bad));
}
console.log("frontend safe.ts: all assertions passed");
