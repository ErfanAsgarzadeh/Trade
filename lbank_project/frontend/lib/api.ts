/** Same-origin, cookie-based transport. A previous session can never publish a late response. */
const messages: Record<number, [string, string]> = {
  401: [
    "نام کاربری یا رمز نادرست است، یا نشست شما پایان یافته.",
    "Wrong username or password, or your session has ended.",
  ],
  403: [
    "درخواست تأیید نشد؛ صفحه را تازه کنید.",
    "Request not authorized; refresh the page.",
  ],
  404: [
    "درخواست یا فایل موردنظر پیدا نشد.",
    "The requested item was not found.",
  ],
  409: [
    "درخواست با وضعیت فعلی سازگار نیست؛ وضعیت و درخواست‌های در انتظار را بررسی کنید.",
    "This conflicts with the current state; check the status and pending requests.",
  ],
  422: [
    "اطلاعات واردشده معتبر نیست.",
    "Some of the details entered are not valid.",
  ],
  429: [
    "درخواست‌ها زیاد است؛ کمی بعد دوباره تلاش کنید.",
    "Too many requests; try again shortly.",
  ],
  503: [
    "سرویس مشغول است؛ کمی بعد دوباره تلاش کنید.",
    "The service is busy; try again shortly.",
  ],
};
// Specific server answers worth telling apart from the generic text of their status code.
const details: Record<string, [string, string]> = {
  "Two-factor setup required": [
    "برای تغییرات مدیریتی ابتدا «ورود دومرحله‌ای» را در بخش اطلاعات کاربری پنل خود فعال کنید.",
    "Turn on two-step login in the profile section of your panel before making admin changes.",
  ],
  "Two-factor code required": [
    "کد ورود دومرحله‌ای را وارد کنید.",
    "Enter your two-step login code.",
  ],
  "Invalid two-factor code": [
    "کد دومرحله‌ای نادرست یا مصرف‌شده است؛ کد بعدی برنامه را وارد کنید.",
    "The two-step code is wrong or already used; enter the next code from your app.",
  ],
  "Current password is incorrect": [
    "رمز عبور فعلی نادرست است.",
    "The current password is incorrect.",
  ],
  "Password confirmation does not match": [
    "رمز جدید و تکرار آن یکسان نیستند.",
    "The new password and its confirmation do not match.",
  ],
  "Invalid or expired code": [
    "کد نادرست یا منقضی شده است.",
    "The code is wrong or has expired.",
  ],
  "Too many failed attempts for this account; try again later": [
    "تلاش ناموفق زیاد بود؛ این حساب برای مدتی قفل شده است. بعداً دوباره تلاش کنید.",
    "Too many failed attempts; this account is locked for a while. Try again later.",
  ],
};
// Error text follows the page language set on <html>.
const english = () =>
  typeof document !== "undefined" && document.documentElement.lang === "en";
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail = "",
  ) {
    super(
      details[detail]?.[english() ? 1 : 0] ??
        messages[status]?.[english() ? 1 : 0] ??
        (english() ? "The request failed." : "درخواست انجام نشد."),
    );
  }
}
export class SessionChanged extends Error {
  constructor() {
    super(english() ? "Your session changed." : "نشست تغییر کرده است.");
  }
}
export class ApiClient {
  csrf = "";
  private generation = 0;
  private controllers = new Set<AbortController>();
  onUnauthorized?: () => void;
  constructor(private transport: typeof fetch = (...args) => fetch(...args)) {}
  invalidate() {
    this.generation++;
    this.csrf = "";
    for (const c of this.controllers) c.abort();
    this.controllers.clear();
  }
  async request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
    const epoch = this.generation,
      controller = new AbortController();
    this.controllers.add(controller);
    const headers: Record<string, string> = { "X-Portal-Request": "1" };
    if (method !== "GET") headers["X-CSRF-Token"] = this.csrf;
    // A file is sent as-is (image uploads); anything else as JSON.
    const raw = typeof Blob !== "undefined" && body instanceof Blob;
    if (body !== undefined)
      headers["Content-Type"] = raw ? (body as Blob).type : "application/json";
    try {
      const response = await this.transport(path, {
        method,
        headers,
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
        body:
          body === undefined
            ? undefined
            : raw
              ? (body as Blob)
              : JSON.stringify(body),
      });
      const data = await response.json();
      if (epoch !== this.generation) throw new SessionChanged();
      if (!response.ok) {
        if (response.status === 401) {
          this.invalidate();
          this.onUnauthorized?.();
        }
        throw new ApiError(
          response.status,
          typeof data?.detail === "string" ? data.detail : "",
        );
      }
      return data as T;
    } catch (error) {
      if (epoch !== this.generation && !(error instanceof ApiError))
        throw new SessionChanged();
      throw error;
    } finally {
      this.controllers.delete(controller);
    }
  }
}
/** The server asked for the two-step code at sign-in. */
export const needsTwoFactor = (error: unknown) =>
  error instanceof ApiError &&
  error.status === 401 &&
  error.detail === "Two-factor code required";
export function errorText(error: unknown) {
  return error instanceof Error
    ? error.message
    : english()
      ? "The request failed."
      : "درخواست انجام نشد.";
}
