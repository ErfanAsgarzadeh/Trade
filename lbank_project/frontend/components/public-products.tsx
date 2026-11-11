"use client";
import { useEffect, useState } from "react";
import type { Plans } from "@/lib/types";
export default function PublicProducts() {
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
        ? "فروش باز است؛ طرح‌ها را در پنل ببینید"
        : "فروش فعلاً بسته است"
      : "وضعیت فروش را در پنل ببینید";
  };
  return (
    <div className="landing-product-cards">
      <article>
        <span>SIGNALS</span>
        <h3>فقط سیگنال</h3>
        <p>
          ورود پیشنهادی، حد ضرر، هدف در صورت تعریف و زمان اعتبار؛ بدون نیاز به
          کلید صرافی. تصمیم و اجرای معامله با شماست.
        </p>
        <small>{status("signals")}</small>
      </article>
      <article>
        <span>AUTOTRADE</span>
        <h3>معاملهٔ خودکار</h3>
        <p>
          مجوز ورود و مدیریت معاملات ربات، همراه با سیگنال‌ها. موتور فعلی
          آزمایشی است و سفارش واقعی به صرافی فعال نیست.
        </p>
        <small>{status("autotrade")}</small>
      </article>
    </div>
  );
}
