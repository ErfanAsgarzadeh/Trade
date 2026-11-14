// A small Markdown subset for blog posts. It returns data, never HTML, so a post cannot inject markup or scripts.
export type Inline =
  | { kind: "text"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "link"; text: string; href: string }
  | { kind: "image"; alt: string; src: string; title: string };
export type Block =
  | { kind: "h2" | "h3"; text: string; id: string }
  | { kind: "p" | "quote"; inline: Inline[] }
  | { kind: "ul" | "ol"; items: Inline[][] }
  | { kind: "figure"; alt: string; src: string; title: string };

// Only site paths, anchors and https links; anything else stays plain text.
const SAFE_HREF = /^(\/(?!\/)[^\s]*|#[^\s]+|https:\/\/[^\s]+)$/;

// Only images uploaded to this site: ![alt](/blog-media/<id>.webp "caption").
export const IMAGE_SRC = /^\/blog-media\/[a-f0-9]{16,32}\.webp$/;
const IMAGE = String.raw`!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)`;
const IMAGE_LINE = new RegExp("^" + IMAGE + "$");

export function inline(source: string): Inline[] {
  const out: Inline[] = [];
  const pattern = new RegExp(
    IMAGE + String.raw`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)`,
    "g",
  );
  let last = 0;
  for (const match of source.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (start > last)
      out.push({ kind: "text", text: source.slice(last, start) });
    if (match[2] !== undefined) {
      if (IMAGE_SRC.test(match[2]))
        out.push({
          kind: "image",
          alt: match[1],
          src: match[2],
          title: match[3] ?? "",
        });
      else out.push({ kind: "text", text: match[1] });
    } else if (match[4] !== undefined)
      out.push({ kind: "strong", text: match[4] });
    else if (SAFE_HREF.test(match[6]))
      out.push({ kind: "link", text: match[5], href: match[6] });
    else out.push({ kind: "text", text: match[5] });
    last = start + match[0].length;
  }
  if (last < source.length)
    out.push({ kind: "text", text: source.slice(last) });
  return out;
}

export function slugify(text: string) {
  return (
    text
      .trim()
      .toLowerCase()
      .replace(/[^\p{L}\p{N}\s-]/gu, "")
      .replace(/[\s‌]+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "") || "section"
  );
}

export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  const ids = new Map<string, number>();
  let paragraph: string[] = [];
  let list: { kind: "ul" | "ol"; items: Inline[][] } | null = null;
  const flush = () => {
    if (paragraph.length) {
      const text = paragraph.join(" ");
      if (text.startsWith("> "))
        blocks.push({ kind: "quote", inline: inline(text.slice(2)) });
      else blocks.push({ kind: "p", inline: inline(text) });
      paragraph = [];
    }
    if (list) {
      blocks.push(list);
      list = null;
    }
  };
  for (const raw of source.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trim();
    const heading = /^(##|###) (.+)$/.exec(line);
    const bullet = /^- (.+)$/.exec(line);
    const numbered = /^\d+\. (.+)$/.exec(line);
    const figure = IMAGE_LINE.exec(line);
    if (!line) flush();
    else if (figure) {
      flush();
      if (IMAGE_SRC.test(figure[2]))
        blocks.push({
          kind: "figure",
          alt: figure[1],
          src: figure[2],
          title: figure[3] ?? "",
        });
      else
        blocks.push({ kind: "p", inline: [{ kind: "text", text: figure[1] }] });
    } else if (heading) {
      flush();
      const base = slugify(heading[2]);
      const seen = ids.get(base) ?? 0;
      ids.set(base, seen + 1);
      blocks.push({
        kind: heading[1] === "##" ? "h2" : "h3",
        text: heading[2],
        id: seen ? `${base}-${seen + 1}` : base,
      });
    } else if (bullet || numbered) {
      const kind = bullet ? "ul" : "ol";
      if (paragraph.length || (list && list.kind !== kind)) flush();
      list ??= { kind, items: [] };
      list.items.push(inline((bullet ?? numbered)![1]));
    } else {
      if (list) flush();
      paragraph.push(line);
    }
  }
  flush();
  return blocks;
}

export function readingMinutes(body: string) {
  return Math.max(
    1,
    Math.round(body.split(/\s+/).filter(Boolean).length / 200),
  );
}
