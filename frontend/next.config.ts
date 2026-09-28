import type { NextConfig } from "next";

/**
 * V25.6 — HTTP security headers for the Next.js frontend.
 *
 * What is ENFORCED by default: nosniff, frame protection, Referrer-Policy,
 * Permissions-Policy, HSTS (production only), and the CSP directives that cannot
 * break a working page (object-src, base-uri, frame-ancestors, form-action).
 *
 * NOTE: `headers()` is evaluated at BUILD time, so CSP_ENFORCE (like NEXT_PUBLIC_API_URL) must be
 * present when `next build` runs (Dockerfile: build ARG), not only at `next start`.
 *
 * What is REPORT-ONLY by default: the full script/style/connect CSP. Next.js App
 * Router emits inline bootstrap scripts, so without a per-request nonce the policy
 * has to allow 'unsafe-inline' for scripts, and this policy has not been exercised
 * in a real browser against every page as part of V25.6 (no browser/build was
 * available). Set CSP_ENFORCE=true once the browser console shows no
 * "Content-Security-Policy-Report-Only" violations on the pages you care about.
 *
 * Known limitation (documented in docs/SECURITY.md): because scripts allow
 * 'unsafe-inline', this CSP is defence-in-depth and does NOT by itself stop an XSS
 * bug. Removing that requires nonce support via middleware/proxy, which is
 * intentionally out of scope for V25.6.
 */
const isProd = process.env.NODE_ENV === "production";

function apiOrigin(): string | null {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api/v1").origin;
  } catch {
    return null;
  }
}

function contentSecurityPolicy(): string {
  const connect = ["'self'"];
  const api = apiOrigin();
  if (api) connect.push(api);
  const directives = [
    "default-src 'self'",
    // 'unsafe-eval' is only needed by the Next.js dev server / React refresh.
    `script-src 'self' 'unsafe-inline'${isProd ? "" : " 'unsafe-eval'"}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    `connect-src ${connect.join(" ")}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  return directives.join("; ");
}

const enforceCsp = process.env.CSP_ENFORCE === "true";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  {
    key: enforceCsp ? "Content-Security-Policy" : "Content-Security-Policy-Report-Only",
    value: contentSecurityPolicy(),
  },
  // Always-enforced subset that cannot break rendering.
  ...(enforceCsp
    ? []
    : [
        {
          key: "Content-Security-Policy",
          value: "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        },
      ]),
  ...(isProd ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }] : []),
];

const config: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default config;
