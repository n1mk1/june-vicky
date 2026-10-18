import type { Metadata } from "next";
import { Suspense } from "react";
import { KnowledgeView } from "@/components/kb/KnowledgeView";
import { Loading } from "@/components/ui/States";

export const metadata: Metadata = { title: "Knowledge base" };

export default function KnowledgePage() {
  return (
    // The open note lives in the URL (?n=…), so the view renders on the client inside Suspense.
    <Suspense fallback={<Loading label="Opening the knowledge base" className="p-2" />}>
      <KnowledgeView />
    </Suspense>
  );
}
