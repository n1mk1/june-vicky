import type { Metadata } from "next";
import { Suspense } from "react";
import { ReportView } from "@/components/reports/ReportView";
import { Loading } from "@/components/ui/States";

export const metadata: Metadata = { title: "Report" };

export default function ReportPage({ params }: PageProps<"/reports/[id]">) {
  return (
    // The id is only known at request time, so param access sits inside Suspense (cacheComponents).
    <Suspense fallback={<Loading label="Opening the report" className="p-2" />}>
      <ReportView params={params} />
    </Suspense>
  );
}
