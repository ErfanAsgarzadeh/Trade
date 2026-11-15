import type { Metadata } from "next";
import ForwardTestPage from "@/components/forward-test";
const title = "Avina Forward Test | Live Paper Trading Results";
const description =
  "Daily results of the three Avina bots running in paper mode on real market prices: return, drawdown, win rate and monthly returns. No real money.";
export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description, locale: "en_US" },
  twitter: { title, description },
};
export default function EnglishForwardTest() {
  return <ForwardTestPage lang="en" />;
}
