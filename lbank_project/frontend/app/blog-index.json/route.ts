import { allPosts } from "@/lib/blog";

// Built into out/blog-index.json; the server reads it for sitemap.xml and canonical links.
export const dynamic = "force-static";

export function GET() {
  return Response.json(
    allPosts().map(({ slug, title, description, date, updated, keywords }) => ({
      slug,
      title,
      description,
      date,
      updated,
      keywords,
    })),
  );
}
