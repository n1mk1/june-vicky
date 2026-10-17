import type { Metadata } from "next";
import { Suspense } from "react";
import { Loading } from "@/components/ui/States";
import { IntakeView } from "@/components/truth/IntakeView";

export const metadata: Metadata = { title: "Source of truth" };

export default function IntakePage() {
  return (
    // The flow keeps its place in the URL (?e=…&step=…), so it renders on the client inside Suspense.
    <Suspense fallback={<Loading label="Loading" className="p-2" />}>
      <IntakeView />
    </Suspense>
  );
}
