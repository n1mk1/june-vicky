import type { Metadata } from "next";
import { Suspense } from "react";
import { SimView } from "@/components/sim/SimView";
import { Loading } from "@/components/ui/States";

export const metadata: Metadata = { title: "Simulation" };

export default function SimulationPage() {
  return (
    // The Areopagus builder hands the panel back in the URL (?panel=…&added=…), so the room renders on the client inside Suspense.
    <Suspense fallback={<Loading label="Opening the pitch room" className="p-2" />}>
      <SimView />
    </Suspense>
  );
}
