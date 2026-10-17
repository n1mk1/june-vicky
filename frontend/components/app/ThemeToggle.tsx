"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme, type Theme } from "@/lib/use-theme";
import { cn } from "@/lib/utils";

const OPTIONS: { value: Theme; label: string; Icon: typeof Moon }[] = [
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "light", label: "Light", Icon: Sun },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <div role="radiogroup" aria-label="Colour mode" className="relative flex h-8 shrink-0 rounded-full border border-line-strong p-[3px]">
      <span
        aria-hidden
        className={cn(
          "absolute top-[3px] bottom-[3px] w-[calc(50%-3px)] rounded-full bg-invert-bg transition-transform duration-500 ease-[var(--ease-soft)]",
          theme === "light" ? "translate-x-full" : "translate-x-0",
        )}
      />
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={theme === value}
          onClick={() => setTheme(value)}
          className={cn(
            "relative z-10 flex w-[68px] items-center justify-center gap-1.5 rounded-full font-display text-[12px] uppercase tracking-[-0.02em] transition-colors duration-300",
            theme === value ? "text-invert-ink" : "text-ink-2 hover:text-ink",
          )}
        >
          <Icon className="size-3.5" strokeWidth={1.5} />
          {label}
        </button>
      ))}
    </div>
  );
}
