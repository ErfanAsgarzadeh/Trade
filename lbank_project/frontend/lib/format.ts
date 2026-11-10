export const faNumber = (value: number) =>
  new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 2 }).format(value);
export const usd = (value: number) => faNumber(value) + " دلار";
export const faDate = (value: string | number) =>
  new Date(value).toLocaleDateString("fa-IR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "Asia/Tehran",
  });
export const licenseLabels: Record<string, string> = {
  none: "بدون لایسنس",
  active: "فعال",
  grace: "مهلت ارتقای سرمایه",
  capital_exceeded: "نیازمند ارتقا",
  expired: "پایان اعتبار",
  not_yet_valid: "در انتظار شروع",
};
export const states: Record<string, string> = {
  verified_read_only: "اتصال فقط‌خواندنی تأیید شد",
  saved_unverified: "کلیدها ثبت شدند؛ اتصال هنوز بررسی نشده",
  verification_failed: "اتصال تأیید نشد؛ کلید، مجوز و محدودیت IP را بررسی کنید",
  futures_not_validated: "مشاهدهٔ حساب Futures هنوز تأیید نشده",
  refreshing: "در حال بررسی اتصال",
  busy: "سرویس مشغول است",
  connection_changed: "کلید حساب تغییر کرد",
  not_provisioned: "اجرای اختصاصی هنوز راه‌اندازی نشده",
  not_started: "اجرای ربات شروع نشده",
  running: "پردازش فعال",
  stale: "آخرین بررسی پردازش به‌روز نیست",
  health_unknown: "وضعیت زندهٔ پردازش مشخص نیست",
  unavailable: "وضعیت فعلاً در دسترس نیست",
  queued: "در صف بررسی اتصال",
  retrying: "ارتباط موقتاً قطع است؛ بررسی دوباره انجام می‌شود",
  capability_unavailable: "این نوع حساب فعلاً در دسترس نیست",
};
