import type { Metadata } from "next";
import ForwardTestPage from "@/components/forward-test";
const title = "فوروارد تست آوینا | نتایج زندهٔ شبیه‌سازی کاغذی";
const description =
  "نتایج روزانهٔ اجرای کاغذی (Paper Trading) سه ربات آوینا با قیمت واقعی بازار: بازده، افت سرمایه، نرخ برد و بازده ماهانه؛ بدون پول واقعی.";
export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description, locale: "fa_IR" },
  twitter: { title, description },
};
export default function ForwardTest() {
  return <ForwardTestPage />;
}
