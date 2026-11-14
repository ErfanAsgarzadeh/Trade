"use client";
import { useEffect, useState } from "react";
import type { Plans } from "@/lib/types";
import { useLang } from "@/lib/lang";
export default function PublicProducts() {
  const { t } = useLang();
  const [plans, setPlans] = useState<Plans | null>(null);
  useEffect(() => {
    let current = true;
    fetch("/api/plans", { credentials: "omit", cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw Error("Unavailable");
        return r.json();
      })
      .then((data) => {
        if (current) setPlans(data);
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, []);
  const status = (product: string) => {
    const item = plans?.products.find((p) => p.product === product);
    return item
      ? item.sales_enabled
        ? t(
            "فروش باز است؛ طرح‌ها را در پنل ببینید",
            "Sales are open; see the plans in your panel",
          )
        : t("فروش فعلاً بسته است", "Sales are closed for now")
      : t("وضعیت فروش را در پنل ببینید", "See sales status in your panel");
  };
  return (
    <div className="landing-product-cards">
      <article>
        <span>SIGNALS</span>
        <h3>{t("فقط سیگنال", "Signals only")}</h3>
        <p>
          {t(
            "ورود پیشنهادی، حد ضرر، هدف در صورت تعریف و زمان اعتبار؛ بدون نیاز به کلید صرافی. تصمیم و اجرای معامله با شماست.",
            "Suggested entry, stop-loss, a target where defined, and a validity window; no exchange key needed. The decision and the trade are yours.",
          )}
        </p>
        <small>{status("signals")}</small>
      </article>
      <article>
        <span>AUTOTRADE</span>
        <h3>{t("معاملهٔ خودکار", "Automated trading")}</h3>
        <p>
          {t(
            "مجوز ورود و مدیریت معاملات ربات، همراه با سیگنال‌ها. موتور فعلی آزمایشی است و سفارش واقعی به صرافی فعال نیست.",
            "A license for the bot to enter and manage trades, signals included. The current engine is in trial and does not yet place real exchange orders.",
          )}
        </p>
        <small>{status("autotrade")}</small>
      </article>
    </div>
  );
}
