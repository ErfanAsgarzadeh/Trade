"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiClient } from "@/lib/api";
import type { Robot } from "@/lib/types";
import { num, stateLabel } from "@/lib/format";
import { useLang } from "@/lib/lang";
import { DataTable } from "./shared";
export default function Robots({
  api,
  report,
}: {
  api: ApiClient;
  report: (e: unknown) => void;
}) {
  const { lang, t } = useLang();
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
          <h2>{t("ربات‌های حساب شما", "Your account's bots")}</h2>
          <p>
            {t(
              "عملکرد زیر مربوط به اجرای آزمایشی اختصاصی شماست؛ معاملات واقعی صرافی نیست.",
              "The results below come from your private trial run, not real exchange trades.",
            )}
          </p>
        </div>
        <button
          id="refresh-robots"
          className="secondary"
          disabled={busy}
          onClick={refresh}
        >
          {t("به‌روزرسانی", "Refresh")}
        </button>
      </div>
      <div
        id="execution-readiness"
        className="connection-summary"
        role="status"
      >
        <h3>{t("وضعیت معاملهٔ خودکار · TheTrueTrade", "Automated trading status · TheTrueTrade")}</h3>
        <p>
          {!readiness
            ? t("در حال بررسی…", "Checking…")
            : readiness.status === "signals_only"
              ? t("اشتراک شما فقط برای دریافت سیگنال است.", "Your subscription covers signals only.")
              : readiness.status === "license_required"
                ? t("لایسنس معتبر معاملهٔ خودکار لازم است.", "A valid automated-trading license is required.")
                : readiness.status === "connection_required"
                  ? t(
                      "ابتدا حساب فیوچرز TheTrueTrade را در بخش اتصال حساب ثبت کنید.",
                      "First add your TheTrueTrade futures account in the exchange section.",
                    )
                  : readiness.status === "verification_required"
                    ? t(
                        "بررسی اتصال حساب را انجام دهید؛ نتیجهٔ معتبر باید به‌روز باشد.",
                        "Run the account connection check; a recent valid result is required.",
                      )
                    : t(
                        "اتصال خواندنی حساب تأیید شده؛ اجرای واقعی هنوز آماده نیست.",
                        "Read access is verified; live execution is not ready yet.",
                      )}
        </p>
        <p className="note">
          {t(
            "بررسی موجودی یا داشتن لایسنس، معامله را شروع نمی‌کند. ثبت سفارش تا تکمیل تطبیق حساب، اجرای اختصاصی مشتری و تأیید استاپ صرافی بسته است.",
            "Checking a balance or holding a license does not start trading. Orders stay off until account matching, a dedicated runtime and exchange stop confirmation are complete.",
          )}
        </p>
      </div>
      <div id="robots" className="grid bots">
        {robots.map((r) => (
          <article className="bot" key={r.bot}>
            <h3>{r.name}</h3>
            <p>{stateLabel(r.state, lang) || r.state}</p>
            <p>
              {t("پوزیشن باز: ", "Open positions: ")}
              {num(r.positions.length, lang)}
              {t(" · معاملات اخیر: ", " · Recent trades: ")}
              {num(r.trades.length, lang)}
            </p>
            {r.positions.length > 0 && (
              <>
                <h4>{t("پوزیشن‌های باز", "Open positions")}</h4>
                <DataTable
                  sideColumns={[1]}
                  headers={[
                    t("نماد", "Symbol"),
                    t("جهت", "Side"),
                    t("ورود", "Entry"),
                    t("استاپ", "Stop"),
                  ]}
                  rows={r.positions.map((x) => [
                    x.symbol,
                    x.side,
                    x.entry_price ?? x.entry,
                    x.active_sl ?? x.stop,
                  ])}
                />
              </>
            )}
            {r.trades.length > 0 && (
              <>
                <h4>{t("معاملات اخیر", "Recent trades")}</h4>
                <DataTable
                  sideColumns={[1]}
                  financialColumns={[3]}
                  headers={[
                    t("نماد", "Symbol"),
                    t("جهت", "Side"),
                    t("ورود", "Entry"),
                    t("سود و زیان", "PnL"),
                  ]}
                  rows={r.trades.map((x) => [
                    x.symbol,
                    x.side,
                    x.entry_price ?? x.entry,
                    x.pnl_usd ?? x.pnl,
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
