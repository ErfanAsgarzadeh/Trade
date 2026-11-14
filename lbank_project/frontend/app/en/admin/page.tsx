import type { Metadata } from "next";
import Portal from "@/components/portal";
export const metadata: Metadata = {
  title: "Admin | Avina",
  robots: { index: false, follow: false },
};
export default function EnglishAdmin() {
  return <Portal initialMode="admin" lang="en" />;
}
