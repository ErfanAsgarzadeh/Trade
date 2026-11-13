import assert from "node:assert/strict";
import test from "node:test";
import { inline, parseMarkdown } from "./markdown";

test("blog markdown keeps unsafe links as text and never yields HTML", () => {
  assert.deepEqual(inline("[x](javascript:alert) <b>y</b>"), [
    { kind: "text", text: "x" },
    { kind: "text", text: " <b>y</b>" },
  ]);
  assert.deepEqual(inline("[a](//evil.example) [b](/blog/x/) **c**"), [
    { kind: "text", text: "a" },
    { kind: "text", text: " " },
    { kind: "link", text: "b", href: "/blog/x/" },
    { kind: "text", text: " " },
    { kind: "strong", text: "c" },
  ]);
});

test("headings get unique ids and lists group by type", () => {
  const blocks = parseMarkdown(
    "## حد ضرر\ntext\n## حد ضرر\n- a\n- b\n1. c\n> quote",
  );
  assert.deepEqual(
    blocks.map((b) => b.kind),
    ["h2", "p", "h2", "ul", "ol", "quote"],
  );
  assert.equal(blocks[0].kind === "h2" && blocks[0].id, "حد-ضرر");
  assert.equal(blocks[2].kind === "h2" && blocks[2].id, "حد-ضرر-2");
});
