import type { Metadata, Viewport } from "next";
import "./globals.css";
import { readFileSync } from "node:fs";
import path from "node:path";
import ThemeProvider from "@/components/theme-provider";
const appearanceBootstrap = readFileSync(
  path.join(process.cwd(), "public/portal-assets/appearance.js"),
  "utf8",
);
const title = "آوینا | ربات معامله‌گر هوشمند ارز دیجیتال و فیوچرز";
const description =
  "آوینا (Avina) ربات ترید هوشمند فیوچرز از خانوادهٔ ARTAX است: سه استراتژی، حد ضرر واقعی روی صرافی، مدیریت ریسک خودکار و سرمایه در حساب خودتان.";
// Canonical, og:url and og:image need the site's origin, so portal_frontend.py adds them when it serves the page.
export const metadata: Metadata = {
  title,
  description,
  applicationName: "Avina",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/portal-assets/favicon.png",
    apple: "/portal-assets/apple-touch-icon.png",
  },
  openGraph: {
    type: "website",
    siteName: "Avina",
    locale: "fa_IR",
    title,
    description,
  },
  twitter: { card: "summary_large_image", title, description },
  appleWebApp: {
    capable: true,
    title: "Avina",
    statusBarStyle: "black-translucent",
  },
};
export const viewport: Viewport = {
  themeColor: "#100424",
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
        <link
          rel="preload"
          href="/portal-assets/vazirmatn-arabic.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
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
