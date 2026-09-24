import type { MetadataRoute } from "next";

const PAGES = ["", "/pricing", "/docs", "/security", "/changelog", "/legal/terms", "/legal/privacy", "/legal/refunds"];

export default function sitemap(): MetadataRoute.Sitemap {
  return PAGES.map((path) => ({
    url: `https://mcpaudit.dev${path}`,
    lastModified: new Date(),
    changeFrequency: "monthly" as const,
    priority: path === "" ? 1 : 0.6,
  }));
}
