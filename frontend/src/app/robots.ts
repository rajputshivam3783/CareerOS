const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://careeros.example.com";

export default function robots() {
  return {
    rules: [
      { userAgent: "*", allow: "/", disallow: ["/admin", "/admin-login", "/recruiter", "/recruiter-login", "/dashboard", "/applications"] },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
