import type { Metadata } from "next";
import { PrepView } from "@/components/prep/PrepView";

export const metadata: Metadata = { title: "Preparation" };

export default function PreparationPage() {
  return <PrepView />;
}
