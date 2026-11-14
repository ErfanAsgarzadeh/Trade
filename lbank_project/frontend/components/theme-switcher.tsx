"use client";
import { useId } from "react";
import { useTheme, type Appearance } from "./theme-provider";
import { useLang } from "@/lib/lang";
export default function ThemeSwitcher() {
  const id = useId(),
    { appearance, setAppearance } = useTheme(),
    { t } = useLang();
  return (
    <div className="theme-switcher">
      <label htmlFor={id}>{t("ظاهر", "Theme")}</label>
      <select
        id={id}
        data-theme-switch
        aria-label={t("انتخاب ظاهر", "Choose theme")}
        value={appearance}
        onChange={(e) => setAppearance(e.target.value as Appearance)}
      >
        <option value="dark">{t("تیره", "Dark")}</option>
        <option value="light">{t("روشن", "Light")}</option>
        <option value="system">{t("سیستم", "System")}</option>
      </select>
    </div>
  );
}
