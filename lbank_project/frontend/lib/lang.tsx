"use client";
import { createContext, useContext } from "react";
import { pick, localPath, type Lang } from "./i18n";

const LangContext = createContext<Lang>("fa");

export function LangProvider({
  lang,
  children,
}: {
  lang: Lang;
  children: React.ReactNode;
}) {
  return <LangContext.Provider value={lang}>{children}</LangContext.Provider>;
}

export function useLang() {
  const lang = useContext(LangContext);
  return {
    lang,
    t: pick(lang),
    path: (p: string) => localPath(lang, p),
  };
}
