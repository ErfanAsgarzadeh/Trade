import type { Metadata } from "next";
import Portal from "@/components/portal";
export const metadata: Metadata = {
  title: "Your panel | Avina",
  robots: { index: false, follow: false },
};
export default function EnglishDashboard() {
  return <Portal lang="en" />;
}
