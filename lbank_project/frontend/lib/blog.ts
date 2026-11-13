import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import {
  parseMarkdown,
  readingMinutes,
  splitFrontMatter,
  type Block,
} from "./markdown";

export type Post = {
  slug: string;
  title: string;
  description: string;
  date: string;
  updated: string;
  keywords: string[];
  minutes: number;
  blocks: Block[];
};

const DIRECTORY = path.join(process.cwd(), "content/blog");
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

export function loadPost(slug: string, source: string): Post {
  const { data, body } = splitFrontMatter(source);
  const date = data.date ?? "";
  const updated = data.updated || date;
  if (!SLUG.test(slug) || slug.length > 80)
    throw Error(`Blog slug "${slug}" must be lowercase latin words and dashes`);
  if (!data.title || !data.description)
    throw Error(`Blog post "${slug}" needs a title and a description`);
  if (!DAY.test(date) || !DAY.test(updated))
    throw Error(`Blog post "${slug}" needs dates as YYYY-MM-DD`);
  return {
    slug,
    title: data.title,
    description: data.description,
    date,
    updated,
    keywords: (data.keywords ?? "")
      .split(/[,،]/)
      .map((word) => word.trim())
      .filter(Boolean),
    minutes: readingMinutes(body),
    blocks: parseMarkdown(body),
  };
}

// Newest first. Files whose names start with "_" are drafts and are not published.
export function allPosts(): Post[] {
  return readdirSync(DIRECTORY)
    .filter((name) => name.endsWith(".md") && !name.startsWith("_"))
    .map((name) =>
      loadPost(
        name.slice(0, -3),
        readFileSync(path.join(DIRECTORY, name), "utf8"),
      ),
    )
    .sort(
      (a, b) => b.date.localeCompare(a.date) || a.slug.localeCompare(b.slug),
    );
}

export function persianDate(day: string) {
  return new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(day + "T00:00:00Z"));
}
