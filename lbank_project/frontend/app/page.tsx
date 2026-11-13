import type { Metadata } from "next";
import Landing from "@/components/landing";
export const metadata: Metadata = {
  title: "Avina | ربات معامله‌گر هوشمند ارز دیجیتال",
  description:
    "بک‌تست پنج‌سالهٔ شاهین، موج‌سوار و ققنوس، از ۲۰۲۱ تا پایان ۲۰۲۵؛ مسیر شبیه‌سازی سرمایه، افت سرمایه و فرض‌های پژوهش را بررسی کنید.",
};
export default function Page() {
  return <Landing />;
}
