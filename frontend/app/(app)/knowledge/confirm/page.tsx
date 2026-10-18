import type { Metadata } from "next";
import { Suspense } from "react";
import { ConfirmView } from "@/components/truth/ConfirmView";
import { Loading } from "@/components/ui/States";

export const metadata: Metadata = { title: "Source of truth" };

export default function ConfirmPage() {
  return (
    // The flow keeps its place in the URL (?e=…&step=…), so it renders on the client inside Suspense.
    <Suspense fallback={<Loading label="Loading" className="p-2" />}>
      <ConfirmView />
    </Suspense>
  );
}
