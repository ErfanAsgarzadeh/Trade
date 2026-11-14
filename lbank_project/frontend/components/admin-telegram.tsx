"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiClient, ApiError, errorText } from "@/lib/api";
import { dateTime, num } from "@/lib/format";
import { useLang } from "@/lib/lang";
import { Heading } from "./shared";

interface Status {
  configured: boolean;
  bot_username: string;
  linked: number;
  queued: number;
  worker_seen: number | null;
  last_ok: number | null;
}

export default function AdminTelegram({
  api,
  report,
}: {
  api: ApiClient;
  report: (e: unknown) => void;
}) {
  const { lang, t } = useLang();
  const [status, setStatus] = useState<Status | null>(null),
    [token, setToken] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [note, setNote] = useState("");
  const load = useCallback(
    () =>
      api.request<Status>("/api/admin/telegram").then(setStatus).catch(report),
    [api, report],
  );
  useEffect(() => {
    void load();
  }, [load]);
  async function save(value: string) {
    setBusy(true);
    setNote("");
    try {
      setStatus(
        await api.request<Status>("/api/admin/telegram", "PUT", {
          token: value,
        }),
      );
      setToken("");
      setNote(
        value
          ? t("ربات وصل شد.", "Bot connected.")
          : t("ربات حذف شد.", "Bot removed."),
      );
    } catch (e) {
      setNote(
        e instanceof ApiError && e.status === 502
          ? t(
              "تلگرام توکن را نپذیرفت یا سرور به تلگرام دسترسی ندارد (در ایران تلگرام فیلتر است؛ پروکسی را در TELEGRAM_HTTPS_PROXY تنظیم کنید).",
              "Telegram rejected the token or the server cannot reach Telegram (set a proxy in TELEGRAM_HTTPS_PROXY if it is blocked).",
            )
          : e instanceof ApiError && e.status === 422
            ? t(
                "این شبیه توکن ربات BotFather نیست.",
                "That does not look like a BotFather token.",
              )
            : errorText(e),
      );
    } finally {
      setBusy(false);
    }
  }
  async function broadcast(e: React.FormEvent) {
    e.preventDefault();
    if (
      !window.confirm(
        t(
          "پیام برای همهٔ کاربران متصل فرستاده شود؟",
          "Send this to every linked user?",
        ),
      )
    )
      return;
    setBusy(true);
    try {
      const result = await api.request<{ recipients: number }>(
        "/api/admin/telegram/broadcast",
        "POST",
        {
          text: message,
        },
      );
      setMessage("");
      setNote(
        t(
          `پیام در صف ارسال برای ${num(result.recipients, lang)} نفر قرار گرفت.`,
          `Queued for ${result.recipients} people.`,
        ),
      );
      void load();
    } catch (err) {
      setNote(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel" id="admin-telegram">
      <Heading
        eyebrow="TELEGRAM"
        title={t("ربات تلگرام آوینا", "Avina Telegram bot")}
        description={t(
          "کاربران حسابشان را به ربات شما وصل می‌کنند و سیگنال‌ها، تأیید پرداخت و فعال‌شدن اشتراک را در تلگرام می‌گیرند.",
          "Customers link their account to your bot and receive signals, payment confirmations and activation notices in Telegram.",
        )}
      />
      {status?.configured ? (
        <div className="admin-overview-services">
          <article>
            <h3>{t("ربات", "Bot")}</h3>
            <p>
              <a
                href={`https://t.me/${status.bot_username}`}
                target="_blank"
                rel="noopener"
              >
                <bdi dir="ltr">@{status.bot_username}</bdi>
              </a>
            </p>
          </article>
          <article>
            <h3>{t("کاربران متصل", "Linked users")}</h3>
            <strong>{num(status.linked, lang)}</strong>
            <p className="note">
              {t("پیام در صف: ", "Queued messages: ")}
              {num(status.queued, lang)}
            </p>
          </article>
          <article>
            <h3>{t("سرویس تلگرام", "Telegram service")}</h3>
            <p>
              {status.last_ok
                ? t("آخرین ارتباط موفق: ", "Last contact: ") +
                  dateTime(status.last_ok, lang)
                : t(
                    "هنوز با تلگرام ارتباط نگرفته",
                    "Has not reached Telegram yet",
                  )}
            </p>
            <p className="note">
              {t(
                "در Docker با نام telegram-worker اجرا می‌شود.",
                "Runs in Docker as telegram-worker.",
              )}
            </p>
          </article>
        </div>
      ) : (
        <ol className="admin-steps">
          <li>
            {t(
              "در تلگرام @BotFather را باز کنید و /newbot بزنید.",
              "In Telegram, open @BotFather and send /newbot.",
            )}
          </li>
          <li>
            {t(
              "نام و نام کاربری ربات را بدهید (مثلاً AvinaSignalsBot).",
              "Give the bot a name and username (e.g. AvinaSignalsBot).",
            )}
          </li>
          <li>
            {t(
              "توکنی را که BotFather می‌دهد اینجا وارد کنید.",
              "Paste the token BotFather gives you here.",
            )}
          </li>
        </ol>
      )}
      <form
        className="admin-payment-form"
        onSubmit={(e) => {
          e.preventDefault();
          void save(token.trim());
        }}
      >
        <label htmlFor="telegram-token">
          {status?.configured
            ? t("تعویض توکن ربات", "Replace bot token")
            : t("توکن ربات", "Bot token")}
        </label>
        <input
          id="telegram-token"
          type="password"
          dir="ltr"
          autoComplete="off"
          placeholder="123456789:AA…"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <p className="field-hint">
          {t(
            "توکن رمزنگاری‌شده ذخیره می‌شود و دوباره نمایش داده نمی‌شود. آن را جای دیگری منتشر نکنید.",
            "The token is stored encrypted and never shown again. Do not share it anywhere else.",
          )}
        </p>
        <div className="telegram-actions">
          <button type="submit" disabled={busy || !token.trim()}>
            {t("ذخیره و اتصال ربات", "Save and connect bot")}
          </button>
          {status?.configured && (
            <button
              type="button"
              className="secondary danger"
              disabled={busy}
              onClick={() =>
                window.confirm(t("ربات حذف شود؟", "Remove the bot?")) &&
                save("")
              }
            >
              {t("حذف ربات", "Remove bot")}
            </button>
          )}
        </div>
      </form>
      {status?.configured && (
        <form className="admin-payment-form" onSubmit={broadcast}>
          <label htmlFor="telegram-broadcast">
            {t("پیام همگانی به کاربران متصل", "Message all linked users")}
          </label>
          <textarea
            id="telegram-broadcast"
            rows={4}
            maxLength={3500}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
          <button type="submit" disabled={busy || !message.trim()}>
            {t("ارسال پیام", "Send message")}
          </button>
        </form>
      )}
      {note && (
        <p className="admin-error" role="status">
          {note}
        </p>
      )}
    </section>
  );
}
