import { locale, type Lang } from "./i18n";

export const num = (value: number, lang: Lang = "fa") =>
  new Intl.NumberFormat(locale(lang), { maximumFractionDigits: 2 }).format(
    value,
  );
export const money = (value: number, lang: Lang = "fa") =>
  lang === "en"
    ? "$" +
      new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value)
    : num(value, "fa") + " دلار";
export const percent = (value: number, lang: Lang = "fa", digits = 1) =>
  lang === "en"
    ? value.toFixed(digits) + "%"
    : num(Number(value.toFixed(digits)), "fa") + "٪";
export const longDate = (value: string | number, lang: Lang = "fa") =>
  new Date(value).toLocaleDateString(locale(lang), {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "Asia/Tehran",
  });
export const dateTime = (seconds: number, lang: Lang = "fa") =>
  new Date(seconds * 1000).toLocaleString(locale(lang), {
    timeZone: "Asia/Tehran",
  });

// Persian shorthands kept for existing call sites.
export const faNumber = (value: number) => num(value, "fa");
export const usd = (value: number) => money(value, "fa");
export const faDate = (value: string | number) => longDate(value, "fa");

const LICENSE: Record<string, [string, string]> = {
  none: ["بدون لایسنس", "No license"],
  active: ["فعال", "Active"],
  grace: ["مهلت ارتقای سرمایه", "Capital upgrade grace period"],
  capital_exceeded: ["نیازمند ارتقا", "Upgrade required"],
  expired: ["پایان اعتبار", "Expired"],
  not_yet_valid: ["در انتظار شروع", "Not started yet"],
};
const STATES: Record<string, [string, string]> = {
  verified_read_only: [
    "اتصال فقط‌خواندنی تأیید شد",
    "Read-only connection verified",
  ],
  saved_unverified: [
    "کلیدها ثبت شدند؛ اتصال هنوز بررسی نشده",
    "Keys saved; connection not checked yet",
  ],
  verification_failed: [
    "اتصال تأیید نشد؛ کلید، مجوز و محدودیت IP را بررسی کنید",
    "Connection not verified; check the key, its permissions and IP restriction",
  ],
  futures_not_validated: [
    "مشاهدهٔ حساب Futures هنوز تأیید نشده",
    "Futures account access not verified yet",
  ],
  refreshing: ["در حال بررسی اتصال", "Checking connection"],
  busy: ["سرویس مشغول است", "Service is busy"],
  connection_changed: ["کلید حساب تغییر کرد", "Account key changed"],
  not_provisioned: [
    "اجرای اختصاصی هنوز راه‌اندازی نشده",
    "Dedicated runtime not set up yet",
  ],
  not_started: ["اجرای ربات شروع نشده", "Bot runtime not started"],
  running: ["پردازش فعال", "Running"],
  stale: [
    "آخرین بررسی پردازش به‌روز نیست",
    "Last runtime check is out of date",
  ],
  health_unknown: ["وضعیت زندهٔ پردازش مشخص نیست", "Runtime health unknown"],
  unavailable: ["وضعیت فعلاً در دسترس نیست", "Status unavailable right now"],
  queued: ["در صف بررسی اتصال", "Queued for a connection check"],
  retrying: [
    "ارتباط موقتاً قطع است؛ بررسی دوباره انجام می‌شود",
    "Temporarily unreachable; retrying",
  ],
  capability_unavailable: [
    "این نوع حساب فعلاً در دسترس نیست",
    "This account type is not available yet",
  ],
};
export const licenseLabel = (state: string, lang: Lang = "fa") =>
  LICENSE[state]?.[lang === "en" ? 1 : 0];
export const stateLabel = (state: string, lang: Lang = "fa") =>
  STATES[state]?.[lang === "en" ? 1 : 0];
