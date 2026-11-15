import assert from "node:assert/strict";
import test from "node:test";
import { linePath, withStart } from "./forward";

test("withStart prepends the 100 index one day before the first point", () => {
  const points = withStart({
    available: true,
    series: [
      { d: "2026-05-02", v: 100.5 },
      { d: "2026-05-03", v: 101 },
    ],
  });
  assert.deepEqual(points[0], { d: "2026-05-01", v: 100 });
  assert.equal(points.length, 3);
  assert.deepEqual(withStart({ available: false }), []);
});

test("linePath stays inside the box and handles a flat line", () => {
  const box = { l: 10, r: 10, t: 10, b: 10 };
  const flat = linePath(
    [
      { d: "a", v: 100 },
      { d: "b", v: 100 },
    ],
    200,
    100,
    box,
  );
  assert.match(flat.d, /^M10\.0,/);
  const rising = linePath(
    [
      { d: "a", v: 100 },
      { d: "b", v: 110 },
    ],
    200,
    100,
    box,
  );
  assert.ok(rising.y(110) < rising.y(100));
  assert.ok(rising.y(110) >= 10 && rising.y(100) <= 90);
});
