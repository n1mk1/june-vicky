import type { Metadata } from "next";
import { ReportsList } from "@/components/reports/ReportsList";

export const metadata: Metadata = { title: "Reports" };

export default function ReportsPage() {
  return <ReportsList />;
}
