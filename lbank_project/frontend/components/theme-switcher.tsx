"use client";
import { useId } from "react";
import { useTheme, type Appearance } from "./theme-provider";
export default function ThemeSwitcher() {
  const id = useId(),
    { appearance, setAppearance } = useTheme();
  return (
    <div className="theme-switcher">
      <label htmlFor={id}>ظاهر</label>
      <select
        id={id}
        data-theme-switch
        aria-label="انتخاب ظاهر"
        value={appearance}
        onChange={(e) => setAppearance(e.target.value as Appearance)}
      >
        <option value="dark">تیره</option>
        <option value="light">روشن</option>
        <option value="system">سیستم</option>
      </select>
    </div>
  );
}
