import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      // Shared reports and the app itself are nobody's search result.
      { userAgent: "*", allow: "/", disallow: ["/app/", "/share/"] },
    ],
    sitemap: "https://mcpaudit.dev/sitemap.xml",
  };
}
