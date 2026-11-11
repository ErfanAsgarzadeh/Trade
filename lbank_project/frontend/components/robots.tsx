"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiClient } from "@/lib/api";
import type { Robot } from "@/lib/types";
import { states } from "@/lib/format";
import { DataTable } from "./shared";
export default function Robots({
  api,
  report,
}: {
  api: ApiClient;
  report: (e: unknown) => void;
}) {
  const [readiness, setReadiness] = useState<{
    status: string;
    checks: {
      autotrade_license: boolean;
      thetruetrade_futures: boolean;
      account_read_verified: boolean;
    };
  } | null>(null);
  const refreshReadiness = useCallback(
    async () => setReadiness(await api.request("/api/me/execution-readiness")),
    [api],
  );
  const [robots, setRobots] = useState<Robot[]>([]),
    [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const data = await api.request<{ robots: Robot[] }>("/api/me/robots");
      setRobots(data.robots);
      await refreshReadiness();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }, [api, report, refreshReadiness]);
  useEffect(() => {
    let mounted = true;
    api
      .request<typeof readiness>("/api/me/execution-readiness")
      .then((data) => {
        if (mounted) setReadiness(data);
      })
      .catch((e) => {
        if (mounted) report(e);
      });
    api
      .request<{ robots: Robot[] }>("/api/me/robots")
      .then((data) => {
        if (mounted) setRobots(data.robots);
      })
      .catch((e) => {
        if (mounted) report(e);
      });
    return () => {
      mounted = false;
    };
  }, [api, report]);
  return (
    <section id="robot-section" className="panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">THREE DIFFERENT PERSPECTIVES</span>
          <h2>ربات‌های حساب شما</h2>
          <p>
            عملکرد زیر مربوط به اجرای آزمایشی اختصاصی شماست؛ معاملات واقعی صرافی
            نیست.
          </p>
        </div>
        <button
          id="refresh-robots"
          className="secondary"
          disabled={busy}
          onClick={refresh}
        >
          به‌روزرسانی ↻
        </button>
      </div>
      <div
        id="execution-readiness"
        className="connection-summary"
        role="status"
      >
        <h3>وضعیت معاملهٔ خودکار · TheTrueTrade</h3>
        <p>
          {!readiness
            ? "در حال بررسی…"
            : readiness.status === "signals_only"
              ? "اشتراک شما فقط برای دریافت سیگنال است."
              : readiness.status === "license_required"
                ? "لایسنس معتبر معاملهٔ خودکار لازم است."
                : readiness.status === "connection_required"
                  ? "ابتدا حساب فیوچرز TheTrueTrade را در بخش اتصال حساب ثبت کنید."
                  : readiness.status === "verification_required"
                    ? "بررسی اتصال حساب را انجام دهید؛ نتیجهٔ معتبر باید به‌روز باشد."
                    : "اتصال خواندنی حساب تأیید شده؛ اجرای واقعی هنوز آماده نیست."}
        </p>
        <p className="note">
          بررسی موجودی یا داشتن لایسنس، معامله را شروع نمی‌کند. ثبت سفارش تا
          تکمیل تطبیق حساب، اجرای اختصاصی مشتری و تأیید استاپ صرافی بسته است.
        </p>
      </div>
      <div id="robots" className="grid bots">
        {robots.map((r) => (
          <article className="bot" key={r.bot}>
            <h3>{r.name}</h3>
            <p>{states[r.state] || r.state}</p>
            <p>
              پوزیشن باز: {r.positions.length} · معاملات اخیر: {r.trades.length}
            </p>
            {r.positions.length > 0 && (
              <>
                <h4>پوزیشن‌های باز</h4>
                <DataTable
                  sideColumns={[1]}
                  headers={["نماد", "جهت", "ورود", "استاپ"]}
                  rows={r.positions.map((t) => [
                    t.symbol,
                    t.side,
                    t.entry_price ?? t.entry,
                    t.active_sl ?? t.stop,
                  ])}
                />
              </>
            )}
            {r.trades.length > 0 && (
              <>
                <h4>معاملات اخیر</h4>
                <DataTable
                  sideColumns={[1]}
                  financialColumns={[3]}
                  headers={["نماد", "جهت", "ورود", "سود و زیان"]}
                  rows={r.trades.map((t) => [
                    t.symbol,
                    t.side,
                    t.entry_price ?? t.entry,
                    t.pnl_usd ?? t.pnl,
                  ])}
                />
              </>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
