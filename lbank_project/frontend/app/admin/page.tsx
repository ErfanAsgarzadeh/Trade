import type { Metadata } from "next";
import Portal from "@/components/portal";
export const metadata: Metadata = {
  title: "کارتابل مدیریت | Avina",
  robots: { index: false, follow: false },
};
export default function AdminPage() {
  return <Portal initialMode="admin" />;
}
