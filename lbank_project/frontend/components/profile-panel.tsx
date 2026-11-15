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
  onEmail,
  totpEnabled,
  onTotp,
  notify,
  report,
}: {
  api: ApiClient;
  email: string | null;
  onEmail: (email: string) => void;
  totpEnabled: boolean;
  onTotp: (enabled: boolean) => void;
  notify: (message: string) => void;
  report: (error: unknown) => void;
}) {
  const { t } = useLang();
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
        { email: value, current_password: password },
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
