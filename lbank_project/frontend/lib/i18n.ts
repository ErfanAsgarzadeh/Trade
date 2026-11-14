// Persian is served at the site root and English under /en. Strings live next to the code that uses them as
// t("فارسی", "English") pairs, so a missing translation is visible in review rather than hidden in a catalog.
export type Lang = "fa" | "en";
export const LANGS: Lang[] = ["fa", "en"];

export const pick =
  (lang: Lang) =>
  (fa: string, en: string): string =>
    lang === "en" ? en : fa;

/** A site path in the given language: "/blog/" becomes "/en/blog/" in English. */
export function localPath(lang: Lang, path: string) {
  const clean = path.startsWith("/en/") || path === "/en" ? path.slice(3) || "/" : path;
  return lang === "en" ? "/en" + (clean === "/" ? "/" : clean) : clean;
}

/** The same page in the other language. */
export function otherPath(lang: Lang, path: string) {
  return localPath(lang === "fa" ? "en" : "fa", path);
}

export const dir = (lang: Lang) => (lang === "en" ? "ltr" : "rtl");
export const locale = (lang: Lang) => (lang === "en" ? "en-US" : "fa-IR");
