import type { Metadata } from "next";
import Portal from "@/components/portal";
export const metadata: Metadata = { title: "ثبت‌نام | Avina" };
export default function Register() {
  return <Portal initialMode="register" />;
}
