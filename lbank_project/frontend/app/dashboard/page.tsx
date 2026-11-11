import type { Metadata } from "next";
import Portal from "@/components/portal";
export const metadata: Metadata = {
  title: "پنل اختصاصی | Trade",
  robots: { index: false, follow: false },
};
export default function Dashboard() {
  return <Portal />;
}
