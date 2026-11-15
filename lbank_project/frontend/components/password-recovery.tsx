"use client";
import { useState } from "react";
import { ApiClient, ApiError, errorText } from "@/lib/api";
import { useLang } from "@/lib/lang";

/** Two steps: ask for a code (sent to the linked Telegram), then set a new password with it. */
export default function PasswordRecovery({
  api,
  initialUsername,
  onDone,
  onCancel,
}: {
  api: ApiClient;
  initialUsername: string;
  onDone: (message: string) => void;
  onCancel: () => void;
}) {
  const { t } = useLang();
  const [step, setStep] = useState<1 | 2>(1),
    [username, setUsername] = useState(initialUsername),
    [busy, setBusy] = useState(false),
    [note, setNote] = useState("");
  async function ask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNote("");
    try {
      await api.request("/api/password-reset/request", "POST", { username });
      setStep(2);
    } catch (error) {
      setNote(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  async function reset(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setNote("");
    if (data.get("new_password") !== data.get("new_password_confirmation")) {
      setNote(
        t("رمز جدید و تکرار آن یکسان نیستند.", "The passwords do not match."),
      );
      return;
    }
    setBusy(true);
    try {
      await api.request("/api/password-reset/confirm", "POST", {
        username,
        code: String(data.get("code") ?? "").trim(),
        new_password: data.get("new_password"),
        new_password_confirmation: data.get("new_password_confirmation"),
      });
      onDone(
        t(
          "رمز عبور تغییر کرد؛ با رمز جدید وارد شوید.",
          "Password changed; sign in with the new password.",
        ),
      );
    } catch (error) {
      setNote(
        error instanceof ApiError && error.status === 403
          ? t(
              "کد نادرست یا منقضی شده است. اگر چند بار اشتباه زدید، کد جدید بخواهید.",
              "The code is wrong or has expired. After several wrong tries, ask for a new code.",
            )
          : errorText(error),
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div id="recovery-panel">
      <h3>{t("بازیابی رمز عبور", "Recover your password")}</h3>
      <p className="note">
        {t(
          "بازیابی فقط وقتی کار می‌کند که تلگرام را به حساب خود وصل کرده باشید؛ کد به همان تلگرام فرستاده می‌شود. در غیر این صورت با پشتیبانی تماس بگیرید.",
          "Recovery only works if you linked Telegram to your account; the code is sent there. Otherwise contact support.",
        )}
      </p>
      {step === 1 ? (
        <form id="recovery-request-form" onSubmit={ask}>
          <label htmlFor="recovery-username">
            {t("نام کاربری", "Username")}
          </label>
          <input
            id="recovery-username"
            dir="ltr"
            autoComplete="username"
            pattern="[a-z](?:[a-z0-9]|-)+"
            minLength={2}
            maxLength={40}
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <button type="submit" className="full" disabled={busy}>
            {t("ارسال کد به تلگرام", "Send code to Telegram")}
          </button>
        </form>
      ) : (
        <form id="recovery-confirm-form" onSubmit={reset} autoComplete="off">
          <p className="note" role="status">
            {t(
              "اگر حسابی با این نام و تلگرام وصل‌شده وجود داشته باشد، کد ۸ رقمی تا ۱۰ دقیقه معتبر فرستاده شد.",
              "If an account with that name and a linked Telegram exists, an 8-digit code valid for 10 minutes was sent.",
            )}
          </p>
          <label htmlFor="recovery-code">
            {t("کد ۸ رقمی", "8-digit code")}
          </label>
          <input
            id="recovery-code"
            name="code"
            dir="ltr"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{8}"
            maxLength={8}
            required
          />
          <label htmlFor="recovery-new-password">
            {t("رمز عبور جدید", "New password")}
          </label>
          <input
            id="recovery-new-password"
            name="new_password"
            type="password"
            dir="ltr"
            autoComplete="new-password"
            minLength={12}
            maxLength={128}
            required
          />
          <label htmlFor="recovery-new-password-confirmation">
            {t("تکرار رمز جدید", "Confirm new password")}
          </label>
          <input
            id="recovery-new-password-confirmation"
            name="new_password_confirmation"
            type="password"
            dir="ltr"
            autoComplete="new-password"
            minLength={12}
            maxLength={128}
            required
          />
          <button type="submit" className="full" disabled={busy}>
            {t("تغییر رمز عبور", "Change password")}
          </button>
        </form>
      )}
      {note && (
        <p className="note warning-text" role="alert">
          {note}
        </p>
      )}
      <p className="note login-foot">
        <button
          type="button"
          id="recovery-cancel"
          className="text-button"
          onClick={onCancel}
        >
          {t("بازگشت به ورود", "Back to sign in")}
        </button>
      </p>
    </div>
  );
}
