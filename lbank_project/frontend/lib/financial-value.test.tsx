import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { FinancialValue } from "../components/shared";
test("PnL presentation preserves source precision and exposes signed status without color", () => {
  for (const [value, status, text] of [
    [0.00001234, "profit", "+0.00001234"],
    [-25.25, "loss", "-25.25"],
    ["12.3400", "profit", "+12.3400"],
    ["+5.20", "profit", "+5.20"],
    [0, "neutral", "0"],
  ] as const) {
    const markup = renderToStaticMarkup(
      createElement(FinancialValue, { value }),
    );
    assert.ok(markup.includes("financial-" + status));
    assert.ok(markup.includes("aria-label="));
    assert.ok(markup.includes(">" + text + "</bdi>"));
  }
  assert.equal(
    renderToStaticMarkup(createElement(FinancialValue, { value: null })),
    "<span>—</span>",
  );
});
