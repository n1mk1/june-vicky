import Image from "next/image";
import Link from "next/link";
import { VickyMark } from "@/components/ui/VickyMark";

/** JUNE × VICKY lockup. The JUNE logo is black on transparent, so dark mode inverts it. */
export function Lockup() {
  return (
    <Link href="/" className="flex h-9 shrink-0 items-center gap-2.5 rounded-full pr-1" aria-label="JUNE × VICKY home">
      <Image
        src="/images/june-logo.png"
        alt="JUNE"
        width={606}
        height={248}
        priority
        className="h-4 w-auto dark:invert"
      />
      <span className="text-[13px] text-dim" aria-hidden>
        ×
      </span>
      <span className="flex items-center gap-1 font-display text-[17px] font-semibold tracking-[-0.06em] uppercase">
        <VickyMark className="size-[15px]" />
        Vicky
      </span>
    </Link>
  );
}
