import Image from "next/image";
import Link from "next/link";

/**
 * JUNE × VICKY lockup from the brand set. Both variants are in the markup and the
 * `dark:` variant (keyed to <html data-theme>) shows one, so a theme switch never flashes.
 */
export function Lockup() {
  return (
    <Link href="/" className="flex h-9 shrink-0 items-center rounded-[3px] pr-1" aria-label="JUNE × VICKY home">
      <Image
        src="/brand/June_x_Vicky.svg"
        alt=""
        width={1454}
        height={248}
        unoptimized
        loading="eager"
        className="h-[22px] w-auto dark:hidden"
      />
      <Image
        src="/brand/June_x_Vicky_white.svg"
        alt=""
        width={1454}
        height={248}
        unoptimized
        loading="eager"
        className="hidden h-[22px] w-auto dark:block"
      />
    </Link>
  );
}
