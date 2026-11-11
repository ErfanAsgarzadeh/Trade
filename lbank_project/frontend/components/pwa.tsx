"use client";
import { useEffect, useState } from "react";
interface InstallEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: string }>;
}
export default function Pwa({ notify }: { notify: (message: string) => void }) {
  const [prompt, setPrompt] = useState<InstallEvent | null>(null);
  useEffect(() => {
    if ("serviceWorker" in navigator)
      navigator.serviceWorker.register("/portal-sw.js").catch(() => {});
    const install = (event: Event) => {
      event.preventDefault();
      setPrompt(event as InstallEvent);
    };
    const installed = () => setPrompt(null);
    const offline = () =>
      notify(
        "اتصال اینترنت قطع است؛ وضعیت نمایش‌داده‌شده ممکن است به‌روز نباشد.",
      );
    const online = () =>
      notify("اتصال برقرار شد؛ برای دریافت آخرین وضعیت، به‌روزرسانی را بزنید.");
    window.addEventListener("beforeinstallprompt", install);
    window.addEventListener("appinstalled", installed);
    window.addEventListener("offline", offline);
    window.addEventListener("online", online);
    return () => {
      window.removeEventListener("beforeinstallprompt", install);
      window.removeEventListener("appinstalled", installed);
      window.removeEventListener("offline", offline);
      window.removeEventListener("online", online);
    };
  }, [notify]);
  if (!prompt) return null;
  return (
    <button
      id="install-app"
      className="secondary small"
      onClick={async () => {
        await prompt.prompt();
        await prompt.userChoice;
        setPrompt(null);
      }}
    >
      نصب اپلیکیشن
    </button>
  );
}
