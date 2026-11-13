import type { Metadata } from "next";
import Portal from "@/components/portal";
const title = "ثبت‌نام در آوینا | ربات معامله‌گر هوشمند";
const description =
  "در کمتر از یک دقیقه حساب آوینا بسازید و به سیگنال‌ها و ربات معامله‌گر هوشمند فیوچرز دسترسی بگیرید.";
export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description },
  twitter: { title, description },
};
export default function Register() {
  return <Portal initialMode="register" />;
}
