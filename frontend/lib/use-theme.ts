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
  dark: { ink: "#e2e2e2", dim: "rgba(216,216,216,0.45)", line: "rgba(255,255,255,0.1)", ember: "#e0502f", bg: "#040508" },
  light: { ink: "#111214", dim: "rgba(17,18,20,0.45)", line: "rgba(17,18,20,0.12)", ember: "#d9432b", bg: "#c8c8c8" },
} as const;
