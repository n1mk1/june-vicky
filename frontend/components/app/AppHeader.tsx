import { Lockup } from "./Lockup";
import { TabNav } from "./TabNav";
import { ThemeToggle } from "./ThemeToggle";

export function AppHeader() {
  return (
    <header className="relative z-20 grid grid-cols-1 items-start gap-3 px-4 pt-4 md:grid-cols-[1fr_auto_1fr] md:px-6">
      <div className="flex items-center gap-3">
        <Lockup />
        <ThemeToggle />
      </div>
      <div className="-mx-4 overflow-x-auto px-4 md:mx-0 md:px-0">
        <TabNav />
      </div>
      <div className="hidden justify-end md:flex">
        <span className="inline-flex h-8 items-center gap-2 rounded-full border border-line px-3.5 text-[12px] text-ink-2">
          <span className="size-1.5 rounded-full bg-ember animate-[pulse-dot_2.4s_ease-in-out_infinite]" aria-hidden />
          Source of truth: Tidewell sample
        </span>
      </div>
    </header>
  );
}
