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
  title: "Avina — ربات معامله‌گر هوشمند | by ARTAX",
  description:
    "آوینا، ربات معامله‌گر هوشمند فیوچرز از خانوادهٔ ARTAX: سه استراتژی شاهین، موج‌سوار و ققنوس با حد ضرر روی خود صرافی و مدیریت ریسک خودکار.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/portal-assets/favicon.png",
    apple: "/portal-assets/apple-touch-icon.png",
  },
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
