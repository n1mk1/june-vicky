"use client";

import { useCallback, useSyncExternalStore } from "react";

export type Theme = "dark" | "light";

function read(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

/** Theme lives on <html data-theme>; the boot script in the root layout restores it before paint. */
export function useTheme() {
  const theme = useSyncExternalStore(subscribe, read, () => "dark" as Theme);

  const setTheme = useCallback((next: Theme) => {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("vicky-theme", next);
    } catch {
      // Storage can be blocked; the theme still applies for this page view.
    }
  }, []);

  return { theme, setTheme };
}

/** Chart and canvas colours, which can't read CSS variables directly. */
export const palette = {
  // Black and white with the orange tertiary accent, as in globals.css.
  dark: { ink: "#ffffff", dim: "rgba(255,255,255,0.42)", line: "rgba(255,255,255,0.14)", ember: "#ff6a13", bg: "#000000" },
  light: { ink: "#000000", dim: "rgba(0,0,0,0.45)", line: "rgba(0,0,0,0.13)", ember: "#c94a00", bg: "#ffffff" },
} as const;
