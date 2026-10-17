"use client";

import { use } from "react";
import { ReportDoc } from "./ReportDoc";

/** Unwraps the route params promise on the client, then renders the report. */
export function ReportView({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <ReportDoc key={id} id={id} />;
}
