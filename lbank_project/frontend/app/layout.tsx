import type { Metadata, Viewport } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Trade — پنل اختصاصی حساب شما",
  description: "مدیریت لایسنس سرمایه‌ای و ربات‌های شاهین، موج‌سوار و ققنوس",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/portal-assets/icon-192.png",
    apple: "/portal-assets/icon-192.png",
  },
  appleWebApp: {
    capable: true,
    title: "Trade",
    statusBarStyle: "black-translucent",
  },
};
export const viewport: Viewport = {
  themeColor: "#101512",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fa" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
