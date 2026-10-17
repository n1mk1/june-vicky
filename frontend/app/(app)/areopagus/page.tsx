import type { Metadata } from "next";
import { Suspense } from "react";
import { AreopagusView } from "@/components/areopagus/AreopagusView";
import { Loading } from "@/components/ui/States";

export const metadata: Metadata = { title: "Areopagus" };

export default function AreopagusPage() {
  return (
    // The builder opens from the URL (?build=1, ?edit=…), so the view renders on the client inside Suspense.
    <Suspense fallback={<Loading label="Gathering the Areopagus" className="p-2" />}>
      <AreopagusView />
    </Suspense>
  );
}
