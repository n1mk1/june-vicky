import type { Metadata } from "next";
import { AreopagusView } from "@/components/areopagus/AreopagusView";

export const metadata: Metadata = { title: "Areopagus" };

export default function AreopagusPage() {
  return <AreopagusView />;
}
