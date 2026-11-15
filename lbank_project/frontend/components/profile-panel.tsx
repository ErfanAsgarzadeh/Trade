"use client";
import { useState } from "react";
import { ApiClient, ApiError, errorText } from "@/lib/api";
import { useLang } from "@/lib/lang";
import { Heading } from "./shared";
import SecurityPanel from "./security-panel";
import TelegramPanel from "./telegram-panel";

export default function ProfilePanel({
  api,
  email,
  emailVerified,
  mailEnabled,
  onEmail,
  totpEnabled,
  onTotp,
  notify,
  report,
}: {
  api: ApiClient;
  email: string | null;
  emailVerified: boolean;
  mailEnabled: boolean;
  onEmail: (email: string) => void;
  totpEnabled: boolean;
  onTotp: (enabled: boolean) => void;
  notify: (message: string) => void;
  report: (error: unknown) => void;
}) {
  const { lang, t } = useLang();
  const [value, setValue] = useState(email ?? ""),
    [password, setPassword] = useState(""),
    [busy, setBusy] = useState(false);
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      const result = await api.request<{ email: string }>(
        "/api/me/email",
        "PUT",
        { email: value, current_password: password, lang },
      );
      setPassword("");
      setValue(result.email);
      onEmail(result.email);
      notify(t("ایمیل ذخیره شد.", "Email saved."));
    } catch (error) {
      if (error instanceof ApiError && error.status === 409)
        notify(
          t(
            "این ایمیل برای حساب دیگری ثبت شده است.",
            "This email belongs to another account.",
          ),
        );
      else if (error instanceof ApiError && error.status === 422)
        notify(t("ایمیل معتبر نیست.", "That email address is not valid."));
      else if (error instanceof ApiError && error.status === 403)
        notify(errorText(error));
      else report(error);
    } finally {
      setBusy(false);
    }
  }
  async function resend() {
    setBusy(true);
    try {
      await api.request("/api/me/email/verify", "POST", { lang });
      notify(
        t(
          "پیوند تأیید به ایمیل شما فرستاده می‌شود؛ چند دقیقه صبر کنید.",
          "A confirmation link is on its way to your email; give it a few minutes.",
        ),
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 429)
        notify(
          t(
            "کمی پیش پیوند فرستاده شد؛ یک دقیقه بعد دوباره امتحان کنید.",
            "A link was just sent; try again in a minute.",
          ),
        );
      else if (error instanceof ApiError && error.status === 409)
        notify(
          t(
            "ایمیل در این سایت فعال نیست یا همین حالا تأیید شده است.",
            "Email is not enabled on this site, or the address is already confirmed.",
          ),
        );
      else report(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section id="profile-section" className="panel">
      <Heading
        eyebrow="PROFILE"
        title={t("اطلاعات کاربری", "Profile")}
        description={t(
          "ایمیل برای اطلاع‌رسانی دربارهٔ اشتراک و پرداخت استفاده می‌شود.",
          "Your email is used for subscription and payment notices.",
        )}
      />
      {!email && (
        <p className="note warning-text">
          {t(
            "هنوز ایمیلی برای حساب شما ثبت نشده است.",
            "Your account has no email yet.",
          )}
        </p>
      )}
      {email && (
        <p className="note" id="email-status" role="status">
          {emailVerified
            ? t("✅ ایمیل تأیید شده است.", "✅ Your email is confirmed.")
            : mailEnabled
              ? t(
                  "ایمیل هنوز تأیید نشده است. بازیابی رمز با ایمیل فقط برای ایمیل تأییدشده کار می‌کند.",
                  "Your email is not confirmed yet. Password recovery by email only works for a confirmed address.",
                )
              : t(
                  "ارسال ایمیل در این سایت فعال نیست؛ تأیید ایمیل و اطلاع‌رسانی با ایمیل فعلاً در دسترس نیست.",
                  "Email sending is not enabled on this site, so email confirmation and email notices are not available.",
                )}
          {!emailVerified && mailEnabled && (
            <>
              {" "}
              <button
                type="button"
                id="resend-verification"
                className="text-button"
                disabled={busy}
                onClick={resend}
              >
                {t("ارسال دوبارهٔ پیوند تأیید", "Resend confirmation link")}
              </button>
            </>
          )}
        </p>
      )}
      <form id="profile-form" className="profile-form" onSubmit={save}>
        <label htmlFor="profile-email">{t("ایمیل", "Email")}</label>
        <div className="profile-row">
          <input
            id="profile-email"
            type="email"
            dir="ltr"
            autoComplete="email"
            maxLength={254}
            required
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <button
            type="submit"
            disabled={busy || !password || value.trim() === (email ?? "")}
          >
            {t("ذخیرهٔ ایمیل", "Save email")}
          </button>
        </div>
        <label htmlFor="profile-password">
          {t(
            "رمز عبور فعلی (برای تأیید تغییر)",
            "Current password (to confirm)",
          )}
        </label>
        <input
          id="profile-password"
          type="password"
          dir="ltr"
          autoComplete="current-password"
          maxLength={128}
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </form>
      <SecurityPanel
        api={api}
        totpEnabled={totpEnabled}
        onTotp={onTotp}
        notify={notify}
      />
      <TelegramPanel api={api} />
    </section>
  );
}
