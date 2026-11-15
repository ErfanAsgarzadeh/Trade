"use client";
import { useLang } from "@/lib/lang";

/** The fresh 6-digit code that sensitive admin changes ask for. */
export default function TotpField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useLang();
  return (
    <>
      <label htmlFor={id}>
        {t(
          "کد ۶ رقمی برنامهٔ احراز هویت (ورود دومرحله‌ای)",
          "6-digit code from your authenticator app (two-step login)",
        )}
      </label>
      <input
        id={id}
        dir="ltr"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]{6}"
        maxLength={6}
        placeholder="123456"
        required
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))}
      />
      <p className="field-hint">
        {t(
          "هر کد فقط یک بار پذیرفته می‌شود؛ اگر فرم خطا داد، کد بعدی برنامه را بزنید.",
          "Each code is accepted once; if the form is refused, use the next code from your app.",
        )}
      </p>
    </>
  );
}
