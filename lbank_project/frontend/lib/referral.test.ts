import assert from "node:assert/strict";
import test from "node:test";
import { captureRef, offerText, rewardText, storedRef } from "./referral";

test("offer and reward sentences describe the program in both languages", () => {
  const offer = {
    type: "percent",
    value: 10,
    purchases: 1,
    window_days: 0,
    min_order_usd: 0,
    products: ["autotrade", "signals"],
  } as const;
  assert.equal(offerText({ ...offer }, "en"), "10% off the first purchase");
  assert.equal(
    offerText(
      { ...offer, type: "fixed", value: 20, purchases: 0, window_days: 30 },
      "en",
    ),
    "$20 off every purchase (within 30 days of sign-up)",
  );
  assert.match(offerText({ ...offer }, "fa"), /تخفیف اولین خرید/);
  assert.equal(offerText({ ...offer, type: "none" }, "en"), "");
  const reward = rewardText(
    {
      type: "credit",
      value: 10,
      trigger: "first",
      max_per_referee: 0,
      hold_days: 7,
      expiry_days: 0,
      max_total_usd: 0,
      min_order_usd: 0,
      products: ["signals"],
      tiers: [{ referrals: 5, value: 20 }],
    },
    "en",
  );
  assert.equal(
    reward.text,
    "You get $10 credit for each friend's first purchase on signal subscriptions (usable after 7 days).",
  );
  assert.deepEqual(reward.tiers, ["From 5 paying friends: $20 credit"]);
});

test("an invite code from a link is remembered and validated", () => {
  const store = new Map<string, string>();
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
  captureRef("?ref=<script>");
  assert.equal(storedRef(), "");
  captureRef("?ref=alice-vip");
  assert.equal(storedRef(), "ALICE-VIP");
});
