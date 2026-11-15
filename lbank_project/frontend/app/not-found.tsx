import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "صفحه پیدا نشد | Page not found",
  robots: { index: false, follow: false },
};

// Both languages on one page: the export is a single 404.html, and the server only switches its lang and direction.
export default function NotFound() {
  return (
    <main className="not-found" id="not-found">
      <span className="eyebrow">404</span>
      <h1 lang="fa" dir="rtl">
        صفحه‌ای که دنبالش بودید پیدا نشد
      </h1>
      <p lang="fa" dir="rtl">
        آدرس را بررسی کنید یا به صفحهٔ اصلی بروید.
      </p>
      <h2 lang="en" dir="ltr">
        This page could not be found
      </h2>
      <p lang="en" dir="ltr">
        Check the address or go to the home page.
      </p>
      <p className="not-found-links">
        <a href="/">آوینا · فارسی</a>
        <a href="/en/" lang="en" dir="ltr">
          Avina · English
        </a>
      </p>
    </main>
  );
}
