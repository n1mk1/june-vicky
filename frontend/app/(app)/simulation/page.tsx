import type { Metadata } from "next";
import { SimView } from "@/components/sim/SimView";

export const metadata: Metadata = { title: "Simulation" };

export default function SimulationPage() {
  return <SimView />;
}
