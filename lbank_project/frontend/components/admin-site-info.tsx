"use client";
import { useEffect, useState } from "react";
import { ApiClient, errorText } from "@/lib/api";
import { useLang } from "@/lib/lang";

type Info = {
  support_email: string;
  telegram_id: string;
  telegram_link: string;
  other_line: string;
};
const empty: Info = {
  support_email: "",
  telegram_id: "",
  telegram_link: "",
  other_line: "",
};

/** Contact details for the public contact page. The legal pages are drafts: the reminder is shown here only. */
export default function AdminSiteInfo({ api }: { api: ApiClient }) {
  const { t } = useLang();
  const [info, setInfo] = useState<Info>(empty),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let current = true;
    api
      .request<Info>("/api/admin/site-info")
      .then((v) => current && setInfo({ ...empty, ...v }))
      .catch((e) => current && setMessage(errorText(e)));
    return () => {
      current = false;
    };
  }, [api]);
  const set = (key: keyof Info) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setInfo({ ...info, [key]: e.target.value });
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      setInfo(await api.request<Info>("/api/admin/site-info", "PUT", info));
      setMessage(t("ذخیره شد.", "Saved."));
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="panel"
      id="admin-site-info"
      aria-labelledby="site-info-title"
    >
      <h2 id="site-info-title">{t("اطلاعات سایت", "Site info")}</h2>
      <p className="note" role="note">
        {t(
          "یادآوری: متن صفحه‌های شرایط استفاده، حریم خصوصی و اعلام ریسک پیش‌نویس است؛ پیش از انتشار نهایی آن‌ها را با یک وکیل بررسی کنید. این یادآوری فقط اینجا نمایش داده می‌شود.",
          "Reminder: the Terms, Privacy and Risk pages are drafts; review them with a lawyer before relying on them. This reminder is shown only here, never on the public pages.",
        )}
      </p>
      <form onSubmit={save}>
        <label htmlFor="si-email">
          {t("ایمیل پشتیبانی", "Support e-mail")}
        </label>
        <input
          id="si-email"
          type="email"
          dir="ltr"
          maxLength={120}
          value={info.support_email}
          onChange={set("support_email")}
        />
        <label htmlFor="si-tg">{t("شناسهٔ تلگرام", "Telegram ID")}</label>
        <input
          id="si-tg"
          dir="ltr"
          maxLength={65}
          placeholder="@avina_support"
          value={info.telegram_id}
          onChange={set("telegram_id")}
        />
        <label htmlFor="si-link">
          {t(
            "پیوند تلگرام (فقط https://t.me/...)",
            "Telegram link (https://t.me/... only)",
          )}
        </label>
        <input
          id="si-link"
          dir="ltr"
          maxLength={120}
          placeholder="https://t.me/avina_support"
          value={info.telegram_link}
          onChange={set("telegram_link")}
        />
        <label htmlFor="si-other">
          {t("راه دیگر (اختیاری)", "Other line (optional)")}
        </label>
        <input
          id="si-other"
          maxLength={160}
          value={info.other_line}
          onChange={set("other_line")}
        />
        <button type="submit" disabled={busy}>
          {t("ذخیره", "Save")}
        </button>
      </form>
      {message && <p role="status">{message}</p>}
    </section>
  );
}
