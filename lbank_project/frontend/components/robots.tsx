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
  const [robots, setRobots] = useState<Robot[]>([]),
    [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const data = await api.request<{ robots: Robot[] }>("/api/me/robots");
      setRobots(data.robots);
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }, [api, report]);
  useEffect(() => {
    let mounted = true;
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
