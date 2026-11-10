import type { Metadata, Viewport } from "next";
import "./globals.css";
import { readFileSync } from "node:fs";
import path from "node:path";
import ThemeProvider from "@/components/theme-provider";
const appearanceBootstrap = readFileSync(
  path.join(process.cwd(), "public/portal-assets/appearance.js"),
  "utf8",
);
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
  themeColor: "#0C101B",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fa" dir="rtl" data-theme="dark" suppressHydrationWarning>
      <head>
        <script
          id="trade-appearance-init"
          dangerouslySetInnerHTML={{ __html: appearanceBootstrap }}
        />
      </head>
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
