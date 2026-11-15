"use client";
import { useState } from "react";
import { ApiClient, ApiError, errorText } from "@/lib/api";
import { useLang } from "@/lib/lang";
import QrCode from "./qr-code";

/** Password change, sign-out of other devices and two-step login (authenticator app) for the signed-in user. */
export default function SecurityPanel({
  api,
  totpEnabled,
  onTotp,
  notify,
}: {
  api: ApiClient;
  totpEnabled: boolean;
  onTotp: (enabled: boolean) => void;
  notify: (message: string) => void;
}) {
  return (
    <div className="security-stack">
      <PasswordCard api={api} notify={notify} />
      <SessionsCard api={api} notify={notify} />
      <TotpCard
        api={api}
        enabled={totpEnabled}
        onChange={onTotp}
        notify={notify}
      />
    </div>
  );
}

function PasswordCard({
  api,
  notify,
}: {
  api: ApiClient;
  notify: (message: string) => void;
}) {
  const { t } = useLang();
  const [busy, setBusy] = useState(false),
    [note, setNote] = useState("");
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget,
      data = new FormData(form);
    setNote("");
    if (data.get("new_password") !== data.get("new_password_confirmation")) {
      setNote(
        t(
          "رمز جدید و تکرار آن یکسان نیستند.",
          "The new password and its confirmation do not match.",
        ),
      );
      return;
    }
    setBusy(true);
    try {
      const result = await api.request<{ csrf: string }>(
        "/api/me/password",
        "PUT",
        {
          current_password: data.get("current_password"),
          new_password: data.get("new_password"),
          new_password_confirmation: data.get("new_password_confirmation"),
        },
      );
      api.csrf = result.csrf;
      form.reset();
      notify(
        t(
          "رمز عبور تغییر کرد و دستگاه‌های دیگر خارج شدند.",
          "Password changed; your other devices were signed out.",
        ),
      );
    } catch (error) {
      setNote(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      id="password-form"
      className="security-card"
      onSubmit={save}
      autoComplete="off"
    >
      <h3>{t("تغییر رمز عبور", "Change password")}</h3>
      <label htmlFor="current-password">
        {t("رمز عبور فعلی", "Current password")}
      </label>
      <input
        id="current-password"
        name="current_password"
        type="password"
        dir="ltr"
        autoComplete="current-password"
        maxLength={128}
        required
      />
      <label htmlFor="new-password">{t("رمز عبور جدید", "New password")}</label>
      <input
        id="new-password"
        name="new_password"
        type="password"
        dir="ltr"
        autoComplete="new-password"
        minLength={12}
        maxLength={128}
        required
      />
      <label htmlFor="new-password-confirmation">
        {t("تکرار رمز جدید", "Confirm new password")}
      </label>
      <input
        id="new-password-confirmation"
        name="new_password_confirmation"
        type="password"
        dir="ltr"
        autoComplete="new-password"
        minLength={12}
        maxLength={128}
        required
      />
      <p className="note">
        {t(
          "رمز حداقل ۱۲ کاراکتر باشد. بعد از تغییر، همهٔ دستگاه‌های دیگر خارج می‌شوند.",
          "Use at least 12 characters. Every other device is signed out after the change.",
        )}
      </p>
      <button type="submit" disabled={busy}>
        {t("تغییر رمز عبور", "Change password")}
      </button>
      {note && (
        <p className="note warning-text" role="alert">
          {note}
        </p>
      )}
    </form>
  );
}

function SessionsCard({
  api,
  notify,
}: {
  api: ApiClient;
  notify: (message: string) => void;
}) {
  const { t } = useLang();
  const [busy, setBusy] = useState(false);
  async function revoke() {
    setBusy(true);
    try {
      const result = await api.request<{ revoked: number }>(
        "/api/me/sessions/revoke-others",
        "POST",
      );
      notify(
        result.revoked
          ? t(
              `${result.revoked} دستگاه دیگر خارج شد.`,
              `${result.revoked} other device(s) signed out.`,
            )
          : t(
              "دستگاه دیگری وارد نشده بود.",
              "There were no other signed-in devices.",
            ),
      );
    } catch (error) {
      notify(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="security-card" id="sessions-card">
      <h3>{t("دستگاه‌های وارد شده", "Signed-in devices")}</h3>
      <p className="note">
        {t(
          "اگر وارد رایانهٔ دیگری شده‌اید یا نگران دسترسی دیگران هستید، همهٔ نشست‌های دیگر را ببندید.",
          "If you signed in on another computer or worry someone else has access, end every other session.",
        )}
      </p>
      <button
        type="button"
        id="revoke-others"
        className="secondary"
        disabled={busy}
        onClick={revoke}
      >
        {t("خروج از دستگاه‌های دیگر", "Sign out other devices")}
      </button>
    </div>
  );
}

type Phase = "idle" | "password" | "scan" | "codes";

function TotpCard({
  api,
  enabled,
  onChange,
  notify,
}: {
  api: ApiClient;
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  notify: (message: string) => void;
}) {
  const { t } = useLang();
  const [phase, setPhase] = useState<Phase>("idle"),
    [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null),
    [codes, setCodes] = useState<string[]>([]),
    [busy, setBusy] = useState(false),
    [note, setNote] = useState("");
  async function begin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setNote("");
    try {
      setSetup(
        await api.request("/api/me/totp/setup", "POST", {
          current_password: data.get("current_password"),
        }),
      );
      setPhase("scan");
    } catch (error) {
      setNote(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  async function confirm(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget,
      data = new FormData(form);
    setBusy(true);
    setNote("");
    try {
      const result = await api.request<{ recovery_codes: string[] }>(
        "/api/me/totp/enable",
        "POST",
        { code: String(data.get("code") ?? "").trim() },
      );
      setCodes(result.recovery_codes);
      setSetup(null);
      setPhase("codes");
      onChange(true);
    } catch (error) {
      setNote(
        error instanceof ApiError && error.status === 403
          ? t(
              "کد نادرست است؛ کد فعلی برنامه را وارد کنید.",
              "That code is not right; enter the current code from your app.",
            )
          : errorText(error),
      );
    } finally {
      setBusy(false);
    }
  }
  async function turnOff(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget,
      data = new FormData(form);
    setBusy(true);
    setNote("");
    try {
      await api.request("/api/me/totp/disable", "POST", {
        current_password: data.get("current_password"),
        code: String(data.get("code") ?? "").trim(),
      });
      form.reset();
      onChange(false);
      setPhase("idle");
      notify(t("ورود دومرحله‌ای خاموش شد.", "Two-step login is off."));
    } catch (error) {
      setNote(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      notify(t("کدهای بازیابی کپی شد.", "Recovery codes copied."));
    } catch {
      notify(
        t(
          "کپی نشد؛ کدها را دستی یادداشت کنید.",
          "Could not copy; write the codes down by hand.",
        ),
      );
    }
  }
  return (
    <div className="security-card" id="totp-card">
      <h3>{t("ورود دومرحله‌ای", "Two-step login")}</h3>
      {phase === "codes" ? (
        <>
          <p className="note warning-text">
            {t(
              "این کدهای بازیابی فقط همین یک بار نمایش داده می‌شوند. هر کد یک بار کار می‌کند؛ اگر گوشی را گم کردید با آن‌ها وارد شوید. جای امنی ذخیره کنید.",
              "These recovery codes are shown only this once. Each works one time if you lose your phone. Store them somewhere safe.",
            )}
          </p>
          <ul id="recovery-codes" className="recovery-codes" dir="ltr">
            {codes.map((c) => (
              <li key={c}>
                <code>{c}</code>
              </li>
            ))}
          </ul>
          <div className="telegram-actions">
            <button
              type="button"
              id="copy-recovery"
              className="secondary"
              onClick={copy}
            >
              {t("کپی کدهای بازیابی", "Copy recovery codes")}
            </button>
            <button
              type="button"
              id="recovery-saved"
              onClick={() => {
                setCodes([]);
                setPhase("idle");
              }}
            >
              {t("ذخیره کردم", "I have saved them")}
            </button>
          </div>
        </>
      ) : enabled ? (
        <form onSubmit={turnOff} id="totp-disable-form" autoComplete="off">
          <p>
            <strong>
              {t("ورود دومرحله‌ای روشن است.", "Two-step login is on.")}
            </strong>
          </p>
          <p className="note">
            {t(
              "برای خاموش‌کردن، رمز عبور و یک کد برنامه (یا کد بازیابی) را وارد کنید.",
              "To turn it off, enter your password and a code from your app (or a recovery code).",
            )}
          </p>
          <label htmlFor="totp-off-password">
            {t("رمز عبور فعلی", "Current password")}
          </label>
          <input
            id="totp-off-password"
            name="current_password"
            type="password"
            dir="ltr"
            autoComplete="current-password"
            maxLength={128}
            required
          />
          <label htmlFor="totp-off-code">{t("کد", "Code")}</label>
          <input
            id="totp-off-code"
            name="code"
            dir="ltr"
            inputMode="text"
            autoComplete="one-time-code"
            maxLength={14}
            required
          />
          <button type="submit" className="secondary" disabled={busy}>
            {t("خاموش‌کردن ورود دومرحله‌ای", "Turn off two-step login")}
          </button>
        </form>
      ) : phase === "scan" && setup ? (
        <form onSubmit={confirm} id="totp-confirm-form" autoComplete="off">
          <p className="note">
            {t(
              "این QR را با یک برنامهٔ احراز هویت (مثل Google Authenticator یا Aegis) اسکن کنید؛ یا کلید زیر را دستی وارد کنید. سپس کد ۶ رقمی را بنویسید.",
              "Scan this QR with an authenticator app (such as Google Authenticator or Aegis), or type the key below. Then enter the 6-digit code.",
            )}
          </p>
          <div className="payment-qr">
            <QrCode
              value={setup.uri}
              label={t("QR ورود دومرحله‌ای", "Two-step login QR code")}
            />
            <bdi id="totp-secret" className="totp-secret" dir="ltr">
              {setup.secret}
            </bdi>
          </div>
          <label htmlFor="totp-code">{t("کد ۶ رقمی", "6-digit code")}</label>
          <input
            id="totp-code"
            name="code"
            dir="ltr"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            required
          />
          <button type="submit" disabled={busy}>
            {t("تأیید و روشن‌کردن", "Confirm and turn on")}
          </button>
        </form>
      ) : phase === "password" ? (
        <form onSubmit={begin} id="totp-start-form" autoComplete="off">
          <label htmlFor="totp-password">
            {t("رمز عبور فعلی", "Current password")}
          </label>
          <input
            id="totp-password"
            name="current_password"
            type="password"
            dir="ltr"
            autoComplete="current-password"
            maxLength={128}
            required
          />
          <button type="submit" disabled={busy}>
            {t("ادامه", "Continue")}
          </button>
        </form>
      ) : (
        <>
          <p className="note">
            {t(
              "با یک برنامهٔ احراز هویت روی گوشی، ورود به حساب شما یک کد ۶ رقمی هم می‌خواهد. برای مدیران سامانه الزامی است.",
              "With an authenticator app on your phone, signing in also needs a 6-digit code. It is required for site administrators.",
            )}
          </p>
          <button
            type="button"
            id="totp-start"
            onClick={() => setPhase("password")}
          >
            {t("فعال‌سازی ورود دومرحله‌ای", "Set up two-step login")}
          </button>
        </>
      )}
      {note && (
        <p className="note warning-text" role="alert">
          {note}
        </p>
      )}
    </div>
  );
}
