"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiClient, errorText } from "@/lib/api";
import { useLang } from "@/lib/lang";

interface Account {
  available: boolean;
  linked: boolean;
  telegram_username: string | null;
  signals: boolean;
  notices: boolean;
}

/** Link this account to the site's Telegram bot; signals and account notices then arrive in Telegram. */
export default function TelegramPanel({ api }: { api: ApiClient }) {
  const { lang, t } = useLang();
  const [account, setAccount] = useState<Account | null>(null),
    [link, setLink] = useState<{ url: string; app_url: string } | null>(null),
    [busy, setBusy] = useState(false),
    [note, setNote] = useState("");
  const load = useCallback(
    () =>
      api
        .request<Account>("/api/me/telegram")
        .then((a) => {
          setAccount(a);
          if (a.linked) setLink(null);
        })
        .catch((e) => setNote(errorText(e))),
    [api],
  );
  useEffect(() => {
    void load();
  }, [load]);
  // After opening the bot, wait for the user to press Start there.
  useEffect(() => {
    if (!link) return;
    const timer = setInterval(load, 4000),
      stop = setTimeout(() => setLink(null), 15 * 60 * 1000);
    return () => {
      clearInterval(timer);
      clearTimeout(stop);
    };
  }, [link, load]);
  async function connect() {
    setBusy(true);
    setNote("");
    try {
      const created = await api.request<{ url: string; app_url: string }>(
        "/api/me/telegram/link",
        "POST",
        { lang },
      );
      setLink(created);
      window.open(created.url, "_blank", "noopener");
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function save(changes: Partial<Account>) {
    if (!account) return;
    setBusy(true);
    try {
      setAccount(
        await api.request<Account>("/api/me/telegram", "PUT", {
          signals: changes.signals ?? account.signals,
          notices: changes.notices ?? account.notices,
        }),
      );
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function unlink() {
    if (!window.confirm(t("اتصال تلگرام قطع شود؟", "Unlink Telegram?"))) return;
    setBusy(true);
    try {
      setAccount(await api.request<Account>("/api/me/telegram", "DELETE"));
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  if (!account || !account.available) return null;
  return (
    <div className="telegram-panel" id="telegram-panel">
      <h3>{t("تلگرام", "Telegram")}</h3>
      {account.linked ? (
        <>
          <p>
            {t("وصل به ", "Linked to ")}
            <bdi dir="ltr">
              {account.telegram_username
                ? "@" + account.telegram_username
                : t("تلگرام شما", "your Telegram")}
            </bdi>
          </p>
          <label className="consent">
            <input
              type="checkbox"
              checked={account.signals}
              disabled={busy}
              onChange={(e) => save({ signals: e.target.checked })}
            />
            {t(
              "سیگنال‌های ربات‌ها در تلگرام ارسال شود (با اشتراک فعال)",
              "Send bot signals to Telegram (with an active subscription)",
            )}
          </label>
          <label className="consent">
            <input
              type="checkbox"
              checked={account.notices}
              disabled={busy}
              onChange={(e) => save({ notices: e.target.checked })}
            />
            {t(
              "اطلاع‌رسانی پرداخت، اشتراک و اخبار آوینا",
              "Payment, subscription and Avina news notices",
            )}
          </label>
          <button
            type="button"
            className="secondary small"
            disabled={busy}
            onClick={unlink}
          >
            {t("قطع اتصال تلگرام", "Unlink Telegram")}
          </button>
        </>
      ) : (
        <>
          <p className="note">
            {t(
              "سیگنال‌ها و اطلاع‌رسانی‌های حساب را مستقیم در تلگرام بگیرید. بعد از زدن دکمه، تلگرام باز می‌شود؛ آنجا Start را بزنید.",
              "Get signals and account notices straight in Telegram. After pressing the button Telegram opens; press Start there.",
            )}
          </p>
          <div className="telegram-actions">
            <button
              type="button"
              id="telegram-connect"
              disabled={busy}
              onClick={connect}
            >
              {t("اتصال تلگرام", "Connect Telegram")}
            </button>
            {link && (
              <a className="button secondary" href={link.app_url}>
                {t("باز کردن در اپ تلگرام", "Open in the Telegram app")}
              </a>
            )}
          </div>
          {link && (
            <p className="note" role="status">
              {t(
                "منتظر زدن Start در تلگرام… این لینک ۱۵ دقیقه معتبر است و فقط یک بار کار می‌کند.",
                "Waiting for Start in Telegram… This link works once and for 15 minutes.",
              )}
            </p>
          )}
        </>
      )}
      {note && <p className="note">{note}</p>}
    </div>
  );
}
