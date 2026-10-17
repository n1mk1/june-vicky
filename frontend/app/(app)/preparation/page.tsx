import type { Metadata } from "next";
import { Suspense } from "react";
import { PrepView } from "@/components/prep/PrepView";
import { Loading } from "@/components/ui/States";

export const metadata: Metadata = { title: "Preparation" };

export default function PreparationPage() {
  return (
    // The live session id lives in the URL (?s=…), so the court renders on the client inside Suspense.
    <Suspense fallback={<Loading label="Opening the court" className="p-2" />}>
      <PrepView />
    </Suspense>
  );
}
