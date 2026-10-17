import { cn } from "@/lib/utils";
import { FILTERS, type FeedFilter } from "./ChatFeed";

export function FeedTabs({ value, onChange }: { value: FeedFilter; onChange: (f: FeedFilter) => void }) {
  return (
    <div role="tablist" aria-label="Show" className="scroll-thin flex gap-1 overflow-x-auto">
      {FILTERS.map((f) => (
        <button
          key={f.value}
          role="tab"
          aria-selected={value === f.value}
          onClick={() => onChange(f.value)}
          className={cn(
            "shrink-0 rounded-full border px-2.5 py-0.5 text-[11.5px] transition-colors",
            value === f.value ? "border-invert-bg bg-invert-bg text-invert-ink" : "border-line text-ink-2 hover:text-ink",
          )}
        >
          {f.label}
        </button>
      ))}
    </div>
  );
}
