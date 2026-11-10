"use client";
import { createContext, useContext, useSyncExternalStore } from "react";
export type Appearance = "dark" | "light" | "system";
declare global {
  interface Window {
    TradeAppearance?: {
      getPreference: () => Appearance;
      setPreference: (value: Appearance) => void;
      subscribe: (listener: () => void) => () => void;
    };
  }
}
const ThemeContext = createContext<{
  appearance: Appearance;
  setAppearance: (value: Appearance) => void;
}>({ appearance: "dark", setAppearance: () => {} });
const subscribe = (listener: () => void) =>
  window.TradeAppearance?.subscribe(listener) || (() => {});
const snapshot = () => window.TradeAppearance?.getPreference() || "dark";
const serverSnapshot = (): Appearance => "dark";
export default function ThemeProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const appearance = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  return (
    <ThemeContext.Provider
      value={{
        appearance,
        setAppearance: (value) => window.TradeAppearance?.setPreference(value),
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}
export function useTheme() {
  return useContext(ThemeContext);
}
