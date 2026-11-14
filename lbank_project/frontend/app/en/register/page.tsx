import type { Metadata } from "next";
import Portal from "@/components/portal";

const title = "Sign up for Avina | Smart Trading Bot";
const description =
  "Create your Avina account in under a minute and get access to signals and the smart futures trading bot.";
export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description, locale: "en_US" },
  twitter: { title, description },
};
export default function EnglishRegister() {
  return <Portal initialMode="register" lang="en" />;
}
