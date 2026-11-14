import { money, num, percent } from "./format";
import type { Lang } from "./i18n";

const KEY = "avina.ref";
const DAYS = 30;

export interface RefereeOffer {
  type: "none" | "percent" | "fixed";
  value: number;
  purchases: number;
  window_days: number;
  min_order_usd: number;
  products: string[];
}
export interface ReferrerReward {
  type: "none" | "credit" | "commission" | "coupon";
  value: number;
  trigger: "first" | "every";
  max_per_referee: number;
  hold_days: number;
  expiry_days: number;
  max_total_usd: number;
  min_order_usd: number;
  products: string[];
  tiers: { referrals: number; value: number }[];
}
export interface ProgramConfig {
  referee: RefereeOffer;
  referrer: ReferrerReward;
}
export interface Discount {
  kind: "referee" | "coupon" | "credit";
  cents: number;
  percent: number | null;
}

/** Remember an invite code from ?ref= for a month, so it survives browsing before sign-up. */
export function captureRef(search: string = window.location.search) {
  const code = new URLSearchParams(search).get("ref");
  if (!code || !/^[A-Za-z0-9][A-Za-z0-9-]{2,23}$/.test(code)) return;
  try {
    localStorage.setItem(
      KEY,
      JSON.stringify({ code: code.toUpperCase(), at: Date.now() }),
    );
  } catch {
    /* storage unavailable: the code still travels in the URL */
  }
}

export function storedRef(): string {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (saved && Date.now() - saved.at < DAYS * 86400000) return saved.code;
  } catch {
    /* ignore */
  }
  return "";
}

export function forgetRef() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

const usd = (v: number, lang: Lang) => money(v, lang);
const pct = (v: number, lang: Lang) => percent(v, lang, v % 1 ? 1 : 0);

function productText(products: string[], lang: Lang) {
  if (products.length !== 1) return "";
  return products[0] === "signals"
    ? lang === "en"
      ? " on signal subscriptions"
      : " روی اشتراک سیگنال"
    : lang === "en"
      ? " on automated trading"
      : " روی معاملهٔ خودکار";
}

/** What an invited friend gets, as one sentence. */
export function offerText(o: RefereeOffer | null | undefined, lang: Lang) {
  if (!o || o.type === "none") return "";
  const amount = o.type === "percent" ? pct(o.value, lang) : usd(o.value, lang);
  const count =
    o.purchases === 0
      ? lang === "en"
        ? "every purchase"
        : "همهٔ خریدها"
      : o.purchases === 1
        ? lang === "en"
          ? "the first purchase"
          : "اولین خرید"
        : lang === "en"
          ? `the first ${o.purchases} purchases`
          : `${num(o.purchases, lang)} خرید اول`;
  const extra = [
    o.min_order_usd > 0
      ? lang === "en"
        ? `orders from ${usd(o.min_order_usd, lang)}`
        : `برای خرید از ${usd(o.min_order_usd, lang)}`
      : "",
    o.window_days > 0
      ? lang === "en"
        ? `within ${o.window_days} days of sign-up`
        : `تا ${num(o.window_days, lang)} روز پس از ثبت‌نام`
      : "",
  ].filter(Boolean);
  return lang === "en"
    ? `${amount} off ${count}${productText(o.products, lang)}${extra.length ? " (" + extra.join(", ") + ")" : ""}`
    : `${amount} تخفیف ${count}${productText(o.products, lang)}${extra.length ? " (" + extra.join("، ") + ")" : ""}`;
}

function rewardAmount(r: ReferrerReward, value: number, lang: Lang) {
  if (r.type === "credit")
    return lang === "en"
      ? `${usd(value, lang)} credit`
      : `${usd(value, lang)} اعتبار خرید`;
  if (r.type === "commission")
    return lang === "en"
      ? `${pct(value, lang)} of their payment as credit`
      : `${pct(value, lang)} مبلغ خرید او به‌صورت اعتبار`;
  return lang === "en"
    ? `a ${pct(value, lang)} discount coupon`
    : `کوپن ${pct(value, lang)} تخفیف`;
}

/** What the inviter earns, as one sentence plus optional tier lines. */
export function rewardText(r: ReferrerReward | null | undefined, lang: Lang) {
  if (!r || r.type === "none") return { text: "", tiers: [] as string[] };
  const when =
    r.trigger === "first"
      ? lang === "en"
        ? "for each friend's first purchase"
        : "به‌ازای اولین خرید هر دوست"
      : r.max_per_referee
        ? lang === "en"
          ? `for each of a friend's first ${r.max_per_referee} purchases`
          : `به‌ازای ${num(r.max_per_referee, lang)} خرید اول هر دوست`
        : lang === "en"
          ? "for every purchase your friends make"
          : "به‌ازای هر خرید دوستانتان";
  const notes = [
    r.hold_days
      ? lang === "en"
        ? `usable after ${r.hold_days} days`
        : `قابل استفاده پس از ${num(r.hold_days, lang)} روز`
      : "",
    r.expiry_days
      ? lang === "en"
        ? `valid for ${r.expiry_days} days`
        : `با اعتبار ${num(r.expiry_days, lang)} روزه`
      : "",
    r.max_total_usd
      ? lang === "en"
        ? `up to ${usd(r.max_total_usd, lang)} in total`
        : `تا سقف ${usd(r.max_total_usd, lang)}`
      : "",
  ].filter(Boolean);
  const text =
    (lang === "en"
      ? `You get ${rewardAmount(r, r.value, lang)} ${when}${productText(r.products, lang)}`
      : `شما ${rewardAmount(r, r.value, lang)} می‌گیرید ${when}${productText(r.products, lang)}`) +
    (notes.length
      ? lang === "en"
        ? " (" + notes.join(", ") + ")"
        : " (" + notes.join("، ") + ")"
      : "") +
    (lang === "en" ? "." : ".");
  const tiers = r.tiers.map((tier) =>
    lang === "en"
      ? `From ${tier.referrals} paying friends: ${rewardAmount(r, tier.value, lang)}`
      : `از ${num(tier.referrals, lang)} دوست خریدار به بعد: ${rewardAmount(r, tier.value, lang)}`,
  );
  return { text, tiers };
}

export function discountLabel(d: Discount, lang: Lang) {
  const share = d.percent ? " " + pct(d.percent, lang) : "";
  if (d.kind === "referee")
    return (lang === "en" ? "Invite discount" : "تخفیف دعوت") + share;
  if (d.kind === "coupon")
    return (lang === "en" ? "Coupon" : "کوپن تخفیف") + share;
  return lang === "en" ? "Credit used" : "اعتبار استفاده‌شده";
}
