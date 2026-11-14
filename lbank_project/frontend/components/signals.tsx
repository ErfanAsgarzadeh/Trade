"use client";
import { useEffect, useState } from "react";
import { ApiClient } from "@/lib/api";
import type { License } from "@/lib/types";
import { dateTime, num } from "@/lib/format";
import { useLang } from "@/lib/lang";
import { Heading } from "./shared";
interface Signal {
  bot: string;
  symbol: string;
  side: string;
  entry: number;
  stop: number;
  target: number | null;
  published_at: number;
  expires_at: number;
  status: string;
  timeframe: string;
}
interface Feed {
  status: string;
  signals: Signal[];
}
const names: Record<string, [string, string]> = {
  main: ["شاهین", "Falcon"],
  c3: ["موج‌سوار", "Wave Rider"],
  pa: ["ققنوس", "Phoenix"],
};
export default function Signals({
  api,
  entitlement,
  report,
}: {
  api: ApiClient;
  entitlement?: License;
  report: (e: unknown) => void;
}) {
  const { lang, t } = useLang();
  const date = (stamp: number) => dateTime(stamp, lang);
  const [feed, setFeed] = useState<Feed | null>(null),
    [refresh, setRefresh] = useState(0),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    let current = true;
    let timer: ReturnType<typeof setTimeout>;
    if (!entitlement?.signals_allowed) {
      setFeed(null);
      return;
    }
    const load = async () => {
      setLoading(true);
      try {
        const data = await api.request<Feed>("/api/me/signals");
        if (current) setFeed(data);
      } catch (e) {
        if (current) report(e);
      } finally {
        if (current) {
          setLoading(false);
          timer = setTimeout(load, 30000);
        }
      }
    };
    void load();
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [api, entitlement, refresh, report]);
  const empty = !entitlement?.signals_allowed
    ? t(
        "برای دریافت سیگنال، اشتراک فعال لازم دارید. پس از تعیین قیمت‌ها می‌توانید نوع اشتراک را انتخاب کنید.",
        "You need an active subscription to receive signals. You can choose one once prices are set.",
      )
    : feed?.status === "not_configured"
      ? t(
          "منبع سیگنال هنوز راه‌اندازی نشده است. سیگنال نمونه یا ساختگی نمایش داده نمی‌شود.",
          "The signal source is not set up yet. No sample or made-up signals are shown.",
        )
      : feed?.status === "unavailable"
        ? t(
            "منبع سیگنال فعلاً در دسترس نیست؛ بعداً به‌روزرسانی کنید.",
            "The signal source is unavailable right now; refresh later.",
          )
        : loading
          ? t("در حال دریافت سیگنال‌ها…", "Loading signals…")
          : t("هنوز سیگنالی از ربات‌ها ثبت نشده است.", "No signals from the bots yet.");
  return (
    <section id="signals-section" className="panel">
      <Heading
        eyebrow="STRATEGY SIGNALS"
        title={t("سیگنال‌های ربات‌ها", "Bot signals")}
        description={t(
          "پیشنهادهای استراتژی برای تصمیم‌گیری شما؛ نمایش سیگنال به معنی انجام معامله نیست.",
          "Strategy suggestions for your own decisions; showing a signal does not place a trade.",
        )}
        number="03 / SIGNALS"
      />
      <div className="actions">
        <span className="quiet-tag">
          {t("به‌روزرسانی هر ۳۰ ثانیه · زمان تهران", "Updates every 30 seconds · Tehran time")}
        </span>
        <button
          id="refresh-signals"
          className="secondary"
          disabled={loading || !entitlement?.signals_allowed}
          onClick={() => setRefresh((v) => v + 1)}
        >
          {t("به‌روزرسانی سیگنال‌ها", "Refresh signals")}
        </button>
      </div>
      {!feed?.signals.length ? (
        <p id="signals-empty" className="empty-state">
          {empty}
        </p>
      ) : (
        <div className="signal-cards">
          {feed.signals.map((s) => (
            <article
              className={"signal-card " + s.status}
              key={[s.bot, s.symbol, s.published_at, s.side].join(":")}
            >
              <div className="signal-title">
                <strong>
                  <bdi>{s.symbol}</bdi>
                </strong>
                <span className="order-status">
                  {s.status === "expired"
                    ? t("منقضی؛ قابل اجرا نیست", "Expired; do not trade")
                    : t("در بازهٔ اعتبار", "Valid now")}
                </span>
              </div>
              <p>
                {names[s.bot]?.[lang === "en" ? 1 : 0] || s.bot} ·{" "}
                <span
                  className={
                    s.side === "long" ? "financial-profit" : "financial-loss"
                  }
                >
                  {s.side === "long"
                    ? t("خرید / Long", "Long")
                    : t("فروش / Short", "Short")}
                </span>{" "}
                · <bdi>{s.timeframe}</bdi>
              </p>
              <dl>
                <div>
                  <dt>{t("ورود پیشنهادی", "Suggested entry")}</dt>
                  <dd>{num(s.entry, lang)}</dd>
                </div>
                <div>
                  <dt>{t("حد ضرر", "Stop-loss")}</dt>
                  <dd>{num(s.stop, lang)}</dd>
                </div>
                <div>
                  <dt>{t("هدف اول", "First target")}</dt>
                  <dd>
                    {s.target === null
                      ? t("مدیریت با استاپ متحرک", "Managed with a trailing stop")
                      : num(s.target, lang)}
                  </dd>
                </div>
              </dl>
              <p className="note">
                {t("ثبت: ", "Published: ")}
                {date(s.published_at)}
                <br />
                {t("پایان اعتبار: ", "Valid until: ")}
                {date(s.expires_at)}
              </p>
            </article>
          ))}
        </div>
      )}
      <p className="note">
        {t(
          "سطوح سیگنال، قیمت تضمین‌شدهٔ اجرا نیستند. سیگنال‌های منقضی برای مرور سابقه‌اند و نباید سفارش جدیدی بر اساس آن‌ها گذاشته شود.",
          "Signal levels are not guaranteed fill prices. Expired signals are for history only; do not place new orders from them.",
        )}
      </p>
    </section>
  );
}
