"use client";

import { useRouter } from "next/navigation";
import { PromptBar } from "@/components/app/PromptBar";
import { OrbScene } from "@/components/fx/scenes";
import { Panel } from "@/components/ui/Panel";
import { ATTACK_LIST } from "@/lib/tidewell";
import { KpiRing } from "./KpiRing";
import { StatCard } from "./StatCard";
import { TrendChart } from "./TrendChart";

const READINESS = 62;

export function DashboardView() {
  const router = useRouter();
  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-12 lg:grid-rows-[minmax(0,1fr)_minmax(0,1fr)_auto]">
      <div className="flex min-h-[300px] lg:col-span-3 lg:row-start-1 [&>*]:flex-1">
        <KpiRing />
      </div>
      <div className="flex lg:col-span-3 lg:row-start-2 [&>*]:flex-1">
        <StatCard />
      </div>

      {/* Center: readiness orb, the dashboard's focal point */}
      <section
        aria-label="Pitch readiness"
        className="relative order-first flex min-h-[380px] items-center justify-center md:col-span-2 lg:order-none lg:col-span-5 lg:col-start-4 lg:row-span-2 lg:row-start-1"
      >
        <div className="absolute inset-0">
          <OrbScene score={READINESS} />
        </div>
        <div className="pointer-events-none relative flex flex-col items-center text-center">
          <span className="label">Pitch readiness</span>
          <span className="display mt-2 text-[clamp(72px,9vw,140px)] tabular-nums">{READINESS}</span>
          <span className="mt-1 max-w-[24ch] text-[12px] text-ink-2">Last practice session, sample. Growth answers pulled it down.</span>
        </div>
      </section>

      <div className="flex min-h-[300px] lg:col-span-4 lg:col-start-9 lg:row-start-1 [&>*]:flex-1">
        <TrendChart />
      </div>
      <div className="flex lg:col-span-4 lg:col-start-9 lg:row-start-2 [&>*]:flex-1">
        <Panel title="What they'll ask first" bodyClassName="scroll-thin overflow-y-auto">
          <ol className="divide-y divide-line">
            {ATTACK_LIST.map((a) => (
              <li key={a.topic} className="flex gap-3 px-4 py-3">
                <span
                  className="mt-1.5 h-1.5 shrink-0 rounded-full bg-ember"
                  style={{ width: 6 + a.severity * 18, opacity: 0.4 + a.severity * 0.6 }}
                  aria-label={`Severity ${Math.round(a.severity * 100)} of 100`}
                  role="img"
                />
                <span>
                  <span className="block font-display text-[16px] tracking-[-0.03em]">{a.topic}</span>
                  <span className="text-[12.5px] text-ink-2">{a.detail}</span>
                </span>
              </li>
            ))}
          </ol>
        </Panel>
      </div>

      <div className="md:col-span-2 lg:col-span-6 lg:col-start-4 lg:row-start-3">
        <PromptBar
          label="Ask about a number"
          placeholder="Ask about a number, e.g. why is burn falling?"
          onSubmit={(text) => {
            try {
              sessionStorage.setItem("vicky-question", text);
            } catch {}
            router.push("/preparation");
          }}
        />
      </div>
    </div>
  );
}
