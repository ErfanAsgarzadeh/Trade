import type { Metadata } from "next";
import Landing from "@/components/landing";

const title = "Avina | Smart Crypto & Futures Trading Bot";
const description =
  "Avina is a smart futures trading bot from ARTAX: three engines, real stop-losses on the exchange, automatic risk management, and your funds stay in your own account.";
export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description, locale: "en_US", type: "website", siteName: "Avina" },
  twitter: { card: "summary_large_image", title, description },
};
export default function EnglishHome() {
  return <Landing lang="en" />;
}
