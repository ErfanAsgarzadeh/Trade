import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
const bootstrap = readFileSync(
  new URL("../public/portal-assets/appearance.js", import.meta.url),
  "utf8",
);
function controller(saved: string | null = null, blocked = false) {
  const attrs = new Map<string, string>();
  const meta = new Map<string, string>();
  const listeners: Record<string, ((event?: any) => void)[]> = {};
  const media = {
    matches: false,
    addEventListener: (_: string, fn: () => void) => {
      listeners.media = [fn];
    },
  };
  const window = {
    matchMedia: () => media,
    addEventListener: (n: string, fn: () => void) => {
      (listeners[n] ??= []).push(fn);
    },
    removeEventListener: (n: string, fn: () => void) => {
      listeners[n] = listeners[n].filter((x) => x !== fn);
    },
    dispatchEvent: (event: Event) => {
      listeners[event.type]?.forEach((fn) => fn());
    },
    TradeAppearance: undefined as any,
  };
  const storage = new Map(saved ? [["trade.appearance", saved]] : []);
  const document = {
    documentElement: {
      setAttribute: (n: string, v: string) => attrs.set(n, v),
    },
    querySelector: () => ({
      setAttribute: (n: string, v: string) => meta.set(n, v),
    }),
    querySelectorAll: () => [],
    addEventListener: () => {},
  };
  vm.runInNewContext(bootstrap, {
    window,
    document,
    Event,
    localStorage: {
      getItem: (k: string) => {
        if (blocked) throw Error("denied");
        return storage.get(k);
      },
      setItem: (k: string, v: string) => {
        if (blocked) throw Error("denied");
        storage.set(k, v);
      },
    },
  });
  return {
    api: window.TradeAppearance,
    attrs,
    meta,
    storage,
    media,
    listeners,
  };
}
test("default dark; stored light applied synchronously before a body exists", () => {
  assert.equal(controller().attrs.get("data-theme"), "dark");
  const c = controller("light");
  assert.equal(c.attrs.get("data-theme"), "light");
  assert.equal(c.meta.get("content"), "#F7F6FA");
  assert.equal(controller("invalid").attrs.get("data-theme"), "dark");
});
test("system follows live media changes; explicit mode ignores them; storage and subscriptions synchronize", () => {
  const c = controller("system");
  assert.equal(c.attrs.get("data-theme"), "light");
  c.media.matches = true;
  c.listeners.media[0]();
  assert.equal(c.attrs.get("data-theme"), "dark");
  let count = 0;
  const off = c.api.subscribe(() => count++);
  c.api.setPreference("light");
  assert.equal(count, 1);
  off();
  assert.equal(c.storage.get("trade.appearance"), "light");
  c.listeners.media[0]();
  assert.equal(c.attrs.get("data-theme"), "light");
  c.listeners.storage[0]({ key: "trade.appearance", newValue: "dark" });
  assert.equal(c.api.getPreference(), "dark");
  c.api.setPreference("invalid");
  assert.equal(c.api.getPreference(), "dark");
});
test("storage denied does not prevent appearance changes", () => {
  const c = controller(null, true);
  c.api.setPreference("light");
  assert.equal(c.attrs.get("data-theme"), "light");
});

test("both base palettes remain exactly the approved AVINA brand values", () => {
  const css = readFileSync(
    new URL("../public/portal-assets/titanium.css", import.meta.url),
    "utf8",
  );
  const keys = [
    "background",
    "surface",
    "surface-elevated",
    "text-primary",
    "text-secondary",
    "primary",
    "primary-foreground",
    "ai-accent",
    "premium-accent",
    "profit",
    "loss",
    "border",
  ];
  const expected = {
    dark: [
      "100424",
      "1a063a",
      "2a0f55",
      "f8f6ff",
      "bcb2db",
      "a767ff",
      "100424",
      "c9b2ff",
      "ffd36b",
      "5be3b5",
      "ff7d9c",
      "3c2670",
    ],
    light: [
      "f8f6ff",
      "ffffff",
      "efe9ff",
      "1a063a",
      "5a5079",
      "5b16c7",
      "ffffff",
      "5a3aa8",
      "8a5a00",
      "05785c",
      "b4234f",
      "e2daf5",
    ],
  };
  for (const theme of ["dark", "light"] as const) {
    const block = css.match(
      new RegExp('\\[data-theme="' + theme + '"\\]\\s*\\{([^}]+)'),
    )![1];
    for (const [i, key] of keys.entries())
      assert.equal(
        block
          .match(new RegExp("--" + key + ":\\s*#([a-fA-F0-9]+)"))![1]
          .toLowerCase(),
        expected[theme][i],
      );
  }
});
