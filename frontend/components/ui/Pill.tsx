import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { RollLabel } from "./RollLabel";

type Variant = "solid" | "outline" | "ghost";

const base =
  "group inline-flex h-8 shrink-0 items-center justify-center gap-2 rounded-full border px-3.5 font-display text-[12.5px] uppercase tracking-[-0.02em] transition-colors duration-300 disabled:pointer-events-none disabled:opacity-40";

const variants: Record<Variant, string> = {
  solid: "border-invert-bg bg-invert-bg text-invert-ink",
  outline: "border-line-strong text-ink hover:border-ink",
  ghost: "border-transparent text-ink-2 hover:text-ink",
};

interface Common {
  label: string;
  variant?: Variant;
  icon?: ReactNode;
  className?: string;
}

export function PillButton({
  label,
  variant = "outline",
  icon,
  className,
  ...props
}: Common & Omit<ComponentProps<"button">, "children">) {
  return (
    <button type="button" className={cn(base, variants[variant], className)} {...props}>
      {icon}
      <RollLabel text={label} />
    </button>
  );
}

export function PillLink({
  label,
  variant = "outline",
  icon,
  className,
  ...props
}: Common & Omit<ComponentProps<typeof Link>, "children">) {
  return (
    <Link className={cn(base, variants[variant], className)} {...props}>
      {icon}
      <RollLabel text={label} />
    </Link>
  );
}
