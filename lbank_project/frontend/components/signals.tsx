"use client";
import { useEffect, useState } from "react";
import { ApiClient } from "@/lib/api";
import type { License } from "@/lib/types";
import { faNumber } from "@/lib/format";
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
const names: Record<string, string> = {
  main: "شاهین",
  c3: "موج‌سوار",
  pa: "ققنوس",
};
const date = (stamp: number) =>
  new Date(stamp * 1000).toLocaleString("fa-IR", { timeZone: "Asia/Tehran" });
export default function Signals({
  api,
  entitlement,
  report,
}: {
  api: ApiClient;
  entitlement?: License;
  report: (e: unknown) => void;
}) {
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
    ? "برای دریافت سیگنال، اشتراک فعال لازم دارید. پس از تعیین قیمت‌ها می‌توانید نوع اشتراک را انتخاب کنید."
    : feed?.status === "not_configured"
      ? "منبع سیگنال هنوز راه‌اندازی نشده است. سیگنال نمونه یا ساختگی نمایش داده نمی‌شود."
      : feed?.status === "unavailable"
        ? "منبع سیگنال فعلاً در دسترس نیست؛ بعداً به‌روزرسانی کنید."
        : loading
          ? "در حال دریافت سیگنال‌ها…"
          : "هنوز سیگنالی از ربات‌ها ثبت نشده است.";
  return (
    <section id="signals-section" className="panel">
      <Heading
        eyebrow="STRATEGY SIGNALS"
        title="سیگنال‌های ربات‌ها"
        description="پیشنهادهای استراتژی برای تصمیم‌گیری شما؛ نمایش سیگنال به معنی انجام معامله نیست."
        number="03 / SIGNALS"
      />
      <div className="actions">
        <span className="quiet-tag">به‌روزرسانی هر ۳۰ ثانیه · زمان تهران</span>
        <button
          id="refresh-signals"
          className="secondary"
          disabled={loading || !entitlement?.signals_allowed}
          onClick={() => setRefresh((v) => v + 1)}
        >
          به‌روزرسانی سیگنال‌ها ↻
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
                    ? "منقضی؛ قابل اجرا نیست"
                    : "در بازهٔ اعتبار"}
                </span>
              </div>
              <p>
                {names[s.bot] || s.bot} ·{" "}
                <span
                  className={
                    s.side === "long" ? "financial-profit" : "financial-loss"
                  }
                >
                  {s.side === "long" ? "خرید / Long" : "فروش / Short"}
                </span>{" "}
                · <bdi>{s.timeframe}</bdi>
              </p>
              <dl>
                <div>
                  <dt>ورود پیشنهادی</dt>
                  <dd>{faNumber(s.entry)}</dd>
                </div>
                <div>
                  <dt>حد ضرر</dt>
                  <dd>{faNumber(s.stop)}</dd>
                </div>
                <div>
                  <dt>هدف اول</dt>
                  <dd>
                    {s.target === null
                      ? "مدیریت با استاپ متحرک"
                      : faNumber(s.target)}
                  </dd>
                </div>
              </dl>
              <p className="note">
                ثبت: {date(s.published_at)}
                <br />
                پایان اعتبار: {date(s.expires_at)}
              </p>
            </article>
          ))}
        </div>
      )}
      <p className="note">
        سطوح سیگنال، قیمت تضمین‌شدهٔ اجرا نیستند. سیگنال‌های منقضی برای مرور
        سابقه‌اند و نباید سفارش جدیدی بر اساس آن‌ها گذاشته شود.
      </p>
    </section>
  );
}
