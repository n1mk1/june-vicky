import { Suspense } from "react";
import { Lockup } from "./Lockup";
import { StatusPill } from "./StatusPill";
import { TabNav, TabNavFallback } from "./TabNav";
import { ThemeToggle } from "./ThemeToggle";

export function AppHeader() {
  return (
    <header className="relative z-20 grid grid-cols-1 items-start gap-3 px-4 pt-4 md:grid-cols-[1fr_auto] md:px-6 xl:grid-cols-[1fr_auto_1fr]">
      <div className="flex items-center gap-3">
        <Lockup />
        <ThemeToggle />
      </div>
      <div className="hidden min-w-0 justify-end md:flex xl:order-last">
        <StatusPill />
      </div>
      <div className="scroll-thin -mx-4 overflow-x-auto px-4 md:col-span-2 md:mx-0 md:px-0 xl:col-span-1">
        <Suspense fallback={<TabNavFallback />}>
          <TabNav />
        </Suspense>
      </div>
    </header>
  );
}
