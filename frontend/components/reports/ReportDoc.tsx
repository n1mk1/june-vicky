"use client";

import { Download } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { EChart } from "@/components/charts/EChart";
import { SourceChip } from "@/components/dashboard/SourceChip";
import { DimBars, type Dim } from "@/components/prep/ChatFeed";
import { ClaimChip } from "@/components/prep/ClaimChip";
import { CitedText } from "@/components/ui/Footnote";
import { CornerMarks } from "@/components/ui/Panel";
import { PillLink } from "@/components/ui/Pill";
import { ErrorNote, Loading } from "@/components/ui/States";
import { VcGlyph } from "@/components/ui/VcGlyph";
import { fmtDate, fmtScore, humanize, sourceLabel } from "@/lib/format";
import type { Figure, PersonaSummary, Report, ReportDims } from "@/lib/types";
import { errorText, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const DIM_ORDER: [keyof ReportDims, string][] = [
  ["accuracy", "Accuracy"],
  ["evidence", "Evidence"],
  ["clarity", "Clarity"],
  ["composure", "Composure"],
  ["investor_fit", "Investor fit"],
];

/** Per-answer scores: accuracy is 0–1, the rest 0–5. */
function answerDims(s: ReportDims | undefined): Dim[] {
  return DIM_ORDER.map(([k, label]) => ({ label, value: s?.[k] ?? null, max: k === "accuracy" ? 1 : 5 }));
}

function figureExplain(f: Figure) {
  return { label: f.label, display: f.display, value: f.value, unit: f.unit, period: f.period, formula: f.formula, source: f.source, kind: f.kind };
}

function Section({ id, title, n, children }: { id: string; title: string; n: number; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-4 flex flex-col gap-4 border-t border-line pt-6">
      <h2 className="flex items-baseline gap-3">
        <span className="label">{String(n).padStart(2, "0")}</span>
        <span className="font-display text-[26px] tracking-[-0.045em]">{title}</span>
      </h2>
      {children}
    </section>
  );
}

function Radar({ dims }: { dims: ReportDims }) {
  const option = useMemo(
    () => ({
      radar: {
        indicator: DIM_ORDER.map(([, name]) => ({ name, max: 5 })),
        radius: "64%",
        splitNumber: 5,
      },
      series: [
        {
          type: "radar",
          symbol: "circle",
          symbolSize: 4,
          areaStyle: { opacity: 0.08 },
          lineStyle: { width: 1.5 },
          data: [{ name: "This session", value: DIM_ORDER.map(([k]) => dims[k] ?? 0) }],
        },
      ],
      tooltip: { trigger: "item" },
    }),
    [dims],
  );
  return (
    <div className="h-[240px] w-full">
      <EChart option={option} ariaLabel={`Scores: ${DIM_ORDER.map(([k, n]) => `${n} ${fmtScore(dims[k])}`).join(", ")}`} />
    </div>
  );
}

export function ReportDoc({ id }: { id: string }) {
  const res = useApi<Report>(`reports/${encodeURIComponent(id)}`);
  const personas = useApi<PersonaSummary[]>("areopagus");
  const glyphs = new Map((personas.data ?? []).map((p) => [p.id, p]));

  if (res.loading && !res.data) return <Loading label="Opening the report" className="p-2" />;
  if (res.status === 404) return <ErrorNote message="That report doesn't exist." className="p-2" />;
  if (res.error && !res.data) return <ErrorNote message={errorText(res.error)} onRetry={res.reload} className="p-2" />;
  const r = res.data;
  if (!r) return null;

  const v = r.verdict;
  const sections = [
    { id: "verdict", title: "Verdict", show: true },
    { id: "panel", title: "The panel", show: r.per_vc?.length > 0 },
    { id: "questions", title: "Question by question", show: r.questions?.length > 0 },
    { id: "ledger", title: "Claims ledger", show: r.ledger?.length > 0 },
    { id: "slides", title: "Slide notes", show: !!r.slides?.length },
    { id: "delivery", title: "Delivery", show: !!r.delivery },
    { id: "knowledge", title: "Knowledge gaps", show: !!r.knowledge_gaps?.length },
    { id: "plan", title: "Action plan", show: r.action_plan?.length > 0 },
    { id: "audit", title: "Audit notes", show: !!r.audit_notes?.length },
    { id: "sources", title: "Sources", show: r.sources?.length > 0 },
  ].filter((s) => s.show);
  const num = (sid: string) => sections.findIndex((s) => s.id === sid) + 1;

  return (
    <div className="scroll-thin -mx-1 min-h-0 flex-1 overflow-y-auto px-1 pb-10">
      <div className="mx-auto grid w-full max-w-[1180px] gap-8 lg:grid-cols-[180px_minmax(0,1fr)]">
        <nav aria-label="Report sections" className="hidden lg:block">
          <ol className="sticky top-2 flex flex-col gap-2 pt-24">
            {sections.map((s, i) => (
              <li key={s.id}>
                <a href={`#${s.id}`} className="font-mono text-[10.5px] uppercase tracking-[-0.04em] text-dim transition-colors hover:text-ink">
                  {String(i + 1).padStart(2, "0")} {s.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>

        <article className="glass relative flex min-w-0 flex-col gap-8 rounded-[4px] p-5 md:p-8">
          <CornerMarks />
          <header className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="label">
                Report · {r.company ?? "Session"} · {fmtDate(r.created_at, true)}
              </span>
              <div className="flex flex-wrap gap-2">
                <a
                  href={`/api/v1/reports/${encodeURIComponent(r.id)}.md`}
                  download={`vicky-report-${r.id.slice(0, 8)}.md`}
                  className="group inline-flex h-8 items-center gap-2 rounded-[3px] border border-line-strong px-3.5 font-mono text-[11px] uppercase tracking-[0.02em] text-ink transition-colors hover:border-ink"
                >
                  <Download className="size-3.5" strokeWidth={1.5} /> Download Markdown
                </a>
                <PillLink href="/preparation" label="Start drill session" variant="solid" />
              </div>
            </div>
            <h1 className="display text-[clamp(40px,5vw,76px)]">{humanize(v.readiness || "Report")}.</h1>
          </header>

          <Section id="verdict" title="Verdict" n={num("verdict")}>
            <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="flex flex-col gap-4">
                <div className="flex items-end gap-3">
                  <span className="display text-[clamp(64px,7vw,104px)] tabular-nums">{fmtScore(v.overall)}</span>
                  <span className="pb-3 text-[13px] text-ink-2">/ 5 overall</span>
                </div>
                <p className="text-[13px] text-ink-2">
                  {v.delta === null || v.delta === undefined ? (
                    "First session for this company."
                  ) : (
                    <>
                      <span className={v.delta < 0 ? "text-ember" : "text-ink"}>
                        {v.delta > 0 ? "+" : v.delta < 0 ? "−" : "±"}
                        {Math.abs(v.delta).toFixed(1)}
                      </span>{" "}
                      since the previous session.
                    </>
                  )}
                  {v.questions ? ` ${v.questions} questions.` : ""}
                </p>
                <DimBars dims={DIM_ORDER.map(([k, label]) => ({ label, value: v.dims?.[k] ?? null }))} />
              </div>
              {v.dims && <Radar dims={v.dims} />}
            </div>
          </Section>

          {r.per_vc?.length > 0 && (
            <Section id="panel" title="The panel" n={num("panel")}>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {r.per_vc.map((p) => {
                  const persona = glyphs.get(p.vc_id);
                  return (
                    <div key={p.vc_id} className="flex flex-col gap-2 rounded-[4px] border border-line p-3.5">
                      <div className="flex items-center gap-2.5">
                        <VcGlyph glyph={persona?.glyph ?? "custom"} />
                        <span className="min-w-0 flex-1">
                          <span className="block font-display text-[17px] tracking-[-0.04em]">{p.name ?? persona?.name ?? p.vc_id}</span>
                          {persona?.firm && <span className="block truncate text-[11px] text-ink-2">{persona.firm}</span>}
                        </span>
                        <span
                          className={cn(
                            "rounded-[3px] border px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[-0.04em]",
                            p.second_meeting ? "border-line-strong text-ink" : "border-ember text-ember",
                          )}
                        >
                          {p.second_meeting ? "Second meeting" : "Passes"}
                        </span>
                      </div>
                      <p className="text-[13px] leading-snug text-ink-2">{p.verdict}</p>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {r.questions?.length > 0 && (
            <Section id="questions" title="Question by question" n={num("questions")}>
              <ol className="flex flex-col gap-6">
                {r.questions.map((q, i) => (
                  <li key={q.turn_id ?? i} className="flex flex-col gap-3 border-l border-line-strong pl-4">
                    <span className="label">
                      Q{i + 1} · {q.vc_name ?? q.vc_id ?? "Panel"}
                      {q.lens ? ` · ${humanize(q.lens)}` : ""}
                    </span>
                    <p className="font-display text-[clamp(18px,1.6vw,22px)] leading-[1.2] tracking-[-0.03em]">
                      <CitedText text={q.question} citations={q.citations ?? []} />
                    </p>
                    {q.why_asked && (
                      <p className="text-[12.5px] text-ink-2">
                        <span className="label mr-1.5">Why asked</span>
                        {q.why_asked}
                      </p>
                    )}
                    <p className="rounded-[4px] bg-surface-solid/50 p-3 text-[13.5px] leading-snug">
                      <span className="label mb-1 block">Your answer</span>
                      {q.answer || <span className="text-dim">No answer.</span>}
                    </p>
                    <DimBars dims={answerDims(q.scores)} />
                    <div className="grid gap-2 text-[13px] leading-snug sm:grid-cols-2">
                      {q.good && (
                        <p>
                          <span className="label mr-1.5">Good</span>
                          <span className="text-ink-2">{q.good}</span>
                        </p>
                      )}
                      {q.missing && (
                        <p>
                          <span className="label mr-1.5">Missing</span>
                          <span className="text-ink-2">{q.missing}</span>
                        </p>
                      )}
                    </div>
                    {q.correct_figure && (
                      <p className="flex flex-wrap items-center gap-2 text-[13px]">
                        <span className="label">Correct figure</span>
                        <span>{q.correct_figure.label}</span>
                        <span className="font-display text-[17px] tracking-[-0.03em] tabular-nums">{q.correct_figure.display}</span>
                        <SourceChip x={figureExplain(q.correct_figure)} />
                      </p>
                    )}
                    {q.strong_answer && (
                      <p className="text-[13.5px] leading-snug">
                        <span className="label mb-1 block">A strong answer</span>
                        {q.strong_answer}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {r.ledger?.length > 0 && (
            <Section id="ledger" title="Claims ledger" n={num("ledger")}>
              <div className="scroll-thin overflow-x-auto">
                <table className="w-full min-w-[560px] border-collapse text-left text-[12.5px]">
                  <thead>
                    <tr className="border-b border-line">
                      <th className="label px-2 py-2 font-normal">You said</th>
                      <th className="label px-2 py-2 font-normal">Status</th>
                      <th className="label px-2 py-2 font-normal">Data says</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {r.ledger.map((c, i) => (
                      <tr key={i} className="align-top">
                        <td className="px-2 py-2.5">
                          &ldquo;{c.text}&rdquo;
                          {c.metric && <span className="block font-mono text-[10px] text-dim">{c.metric}</span>}
                        </td>
                        <td className="px-2 py-2.5">
                          <ClaimChip status={c.status} />
                        </td>
                        <td className="px-2 py-2.5">
                          {c.figure ? (
                            <span className="flex flex-wrap items-center gap-2">
                              <span className="text-ink-2">{c.figure.label}</span>
                              <span className="font-display text-[15px] tracking-[-0.03em] tabular-nums">{c.figure.display}</span>
                              <SourceChip x={figureExplain(c.figure)} align="right" />
                            </span>
                          ) : (
                            <span className="text-ink-2">{c.explanation || "No figure on file."}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          {!!r.slides?.length && (
            <Section id="slides" title="Slide notes" n={num("slides")}>
              <ul className="flex flex-col gap-3">
                {r.slides.map((s, i) => (
                  <li key={i} className="text-[13px]">
                    <span className="label mr-2">Slide {s.slide}</span>
                    {s.note}
                    {s.reword && <span className="mt-1 block text-ink-2">Try: &ldquo;{s.reword}&rdquo;</span>}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {r.delivery && (
            <Section id="delivery" title="Delivery" n={num("delivery")}>
              <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                {typeof r.delivery.talk_time_s === "number" && (
                  <div>
                    <dt className="text-[11px] text-ink-2">Talk time</dt>
                    <dd className="font-display text-[24px] tracking-[-0.04em] tabular-nums">
                      {Math.floor(r.delivery.talk_time_s / 60)}:{String(r.delivery.talk_time_s % 60).padStart(2, "0")}
                    </dd>
                  </div>
                )}
                {typeof r.delivery.fillers === "number" && (
                  <div>
                    <dt className="text-[11px] text-ink-2">Filler words</dt>
                    <dd className="font-display text-[24px] tracking-[-0.04em] tabular-nums">{r.delivery.fillers}</dd>
                  </div>
                )}
              </dl>
            </Section>
          )}

          {!!r.knowledge_gaps?.length && (
            <Section id="knowledge" title="Knowledge gaps" n={num("knowledge")}>
              <div className="grid gap-3 md:grid-cols-2">
                {r.knowledge_gaps.map((k) => (
                  <div key={k.term} className="flex flex-col gap-1.5 rounded-[4px] border border-line p-3.5">
                    <span className="font-display text-[16px] tracking-[-0.03em]">{k.term}</span>
                    <p className="text-[13px] leading-snug text-ink-2">{k.text}</p>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {r.action_plan?.length > 0 && (
            <Section id="plan" title="Action plan" n={num("plan")}>
              <ol className="flex flex-col gap-2.5">
                {[...r.action_plan]
                  .sort((a, b) => a.priority - b.priority)
                  .map((a, i) => (
                    <li key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[13.5px] leading-snug">
                      <span className="font-mono text-[11px] tabular-nums text-dim">{String(i + 1).padStart(2, "0")}</span>
                      <span className="min-w-0 flex-1">{a.text}</span>
                      {a.drill_lens && (
                        <span className="rounded-[3px] border border-line px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[-0.04em] text-ink-2">
                          {humanize(a.drill_lens)}
                        </span>
                      )}
                    </li>
                  ))}
              </ol>
            </Section>
          )}

          {!!r.audit_notes?.length && (
            <Section id="audit" title="Audit notes" n={num("audit")}>
              <ul className="flex flex-col gap-2 text-[13px]">
                {r.audit_notes.map((a, i) => (
                  <li key={i}>
                    {a.changed} <span className="text-ink-2">· {a.why}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {r.sources?.length > 0 && (
            <Section id="sources" title="Sources" n={num("sources")}>
              <ol className="flex flex-col gap-2.5">
                {r.sources.map((s) => (
                  <li key={s.n} className="grid grid-cols-[28px_minmax(0,1fr)] gap-2 text-[12.5px] leading-snug">
                    <span className="font-mono text-[11px] tabular-nums text-dim">{s.n}.</span>
                    <span>
                      <span className="text-ink">{s.label ?? s.title ?? s.publisher ?? sourceLabel(s)}</span>
                      {s.formula && <span className="block text-ink-2">{s.formula}</span>}
                      {s.url ? (
                        <a href={s.url} target="_blank" rel="noreferrer" className="block break-all text-ink-2 underline underline-offset-2 hover:text-ink">
                          {s.publisher ? `${s.publisher} · ` : ""}
                          {s.url}
                          {s.as_of ? ` · ${s.as_of}` : ""}
                        </a>
                      ) : (
                        <span className="block font-mono text-[10px] uppercase tracking-[-0.04em] text-dim">{sourceLabel(s)}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ol>
            </Section>
          )}

          <p className="border-t border-line pt-4 text-center text-[11.5px] text-dim">Synthetic data. No investment advice.</p>
        </article>
      </div>
    </div>
  );
}
