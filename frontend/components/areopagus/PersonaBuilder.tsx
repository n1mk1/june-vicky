"use client";

import { Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Field, inputCls, selectCls } from "@/components/ui/Field";
import { PillButton } from "@/components/ui/Pill";
import { Segmented } from "@/components/ui/Segmented";
import { ErrorNote, Loading } from "@/components/ui/States";
import { VcGlyph } from "@/components/ui/VcGlyph";
import { apiPost, apiPut } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { GenerateResult, PersonaOptions, VCPersonaSpec } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { ChipInput } from "./ChipInput";
import { LensSliders } from "./LensSliders";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]",
]
  .map((s) => `${s}:not([tabindex='-1'])`)
  .join(",");
const MIN_DESC = 10;
const MAX_DESC = 2000;
const EXAMPLE =
  "e.g. A Bay Area SaaS fund partner obsessed with net revenue retention who hates services revenue dressed up as recurring. Blunt, interrupts a lot, and digs three follow-ups deep.";

/** The fields the form edits; everything else on a persona (kits, voice, scoring weights) is left as it is. */
type FormSpec = Pick<
  VCPersonaSpec,
  "name" | "firm" | "archetype" | "glyph" | "bio" | "cheque_role" | "priorities" | "style" | "signature_move" | "method" | "question_seeds" | "dealbreakers"
>;

function toForm(p: VCPersonaSpec): FormSpec {
  return {
    name: p.name ?? "",
    firm: p.firm ?? "",
    archetype: p.archetype ?? "custom",
    glyph: p.glyph ?? "custom",
    bio: p.bio ?? "",
    cheque_role: p.cheque_role ?? "follows",
    priorities: { ...(p.priorities ?? {}) },
    style: {
      tone: p.style?.tone ?? "neutral",
      interrupt_tendency: p.style?.interrupt_tendency ?? 0.4,
      follow_up_depth: p.style?.follow_up_depth ?? 2,
      aggression: p.style?.aggression ?? 0.4,
    },
    signature_move: p.signature_move ?? "",
    method: p.method ?? "",
    question_seeds: [...(p.question_seeds ?? [])],
    dealbreakers: [...(p.dealbreakers ?? [])],
  };
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-t border-line pt-4">
      <h3 className="label">{title}</h3>
      {children}
    </section>
  );
}

function Slider({ id, label, value, onChange }: { id: string; label: string; value: number; onChange: (v: number) => void }) {
  return (
    <Field label={`${label} · ${Math.round(value * 100)}`} htmlFor={id}>
      <input
        id={id}
        type="range"
        min={0}
        max={100}
        step={5}
        value={Math.round(value * 100)}
        onChange={(e) => onChange(Number(e.target.value) / 100)}
        className="h-6 w-full accent-[var(--ember)]"
      />
    </Field>
  );
}

/** The editable persona. Holds its own state, seeded once from `initial` (remount with a new key to reseed). */
function PersonaForm({
  initial,
  options,
  saving,
  error,
  onSave,
  onCancel,
  top,
}: {
  initial: VCPersonaSpec;
  options: PersonaOptions;
  saving: boolean;
  error: string | null;
  onSave: (spec: FormSpec) => void;
  onCancel: () => void;
  top?: ReactNode;
}) {
  const [f, setF] = useState<FormSpec>(() => toForm(initial));
  const set = <K extends keyof FormSpec>(k: K, v: FormSpec[K]) => setF((cur) => ({ ...cur, [k]: v }));
  const setStyle = (patch: Partial<FormSpec["style"]>) => setF((cur) => ({ ...cur, style: { ...cur.style, ...patch } }));
  const roles = options.cheque_roles.includes(f.cheque_role) ? options.cheque_roles : [f.cheque_role, ...options.cheque_roles];

  return (
    <form
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(e) => {
        e.preventDefault();
        if (f.name.trim()) onSave({ ...f, name: f.name.trim() });
      }}
    >
      <div className="scroll-thin flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 pb-5">
        {top}
        <div className="flex items-start gap-3">
          <VcGlyph glyph={f.glyph} className="mt-6 size-9 shrink-0" />
          <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2">
            <Field label="Name" htmlFor="pb-name">
              <input id="pb-name" required maxLength={40} value={f.name} onChange={(e) => set("name", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Firm or role" htmlFor="pb-firm">
              <input id="pb-firm" maxLength={80} value={f.firm} onChange={(e) => set("firm", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Archetype" htmlFor="pb-arch">
              <input id="pb-arch" maxLength={60} value={f.archetype} onChange={(e) => set("archetype", e.target.value)} className={inputCls} />
            </Field>
            <Field label="Cheque role" htmlFor="pb-role">
              <select id="pb-role" value={f.cheque_role} onChange={(e) => set("cheque_role", e.target.value)} className={selectCls}>
                {roles.map((r) => (
                  <option key={r} value={r}>
                    {humanize(r)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </div>

        <Field label="Glyph">
          <div role="radiogroup" aria-label="Glyph" className="flex flex-wrap gap-1.5">
            {options.glyphs.map((g) => (
              <button
                key={g}
                type="button"
                role="radio"
                aria-checked={f.glyph === g}
                aria-label={humanize(g)}
                title={humanize(g)}
                onClick={() => set("glyph", g)}
                className={cn(
                  "flex size-9 items-center justify-center rounded-[3px] border transition-colors",
                  f.glyph === g ? "border-ink bg-surface-solid" : "border-line hover:border-line-strong",
                )}
              >
                <VcGlyph glyph={g} className="size-6" />
              </button>
            ))}
          </div>
        </Field>

        <Field label="Bio" htmlFor="pb-bio">
          <textarea id="pb-bio" rows={3} maxLength={1200} value={f.bio} onChange={(e) => set("bio", e.target.value)} className={cn(inputCls, "h-auto resize-none py-2")} />
        </Field>

        <Section title="Lenses">
          <p className="-mt-1 text-[11.5px] leading-snug text-ink-2">How hard they press on each topic. At 60 and above they also bring that lens&rsquo;s analysis tools.</p>
          <LensSliders lenses={options.lenses} value={f.priorities} onChange={(v) => set("priorities", v)} />
        </Section>

        <Section title="Style">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Tone" htmlFor="pb-tone">
              <input id="pb-tone" maxLength={40} value={f.style.tone} onChange={(e) => setStyle({ tone: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Follow-up depth">
              <Segmented
                label="Follow-up depth"
                value={String(f.style.follow_up_depth) as "1" | "2" | "3"}
                onChange={(v) => setStyle({ follow_up_depth: Number(v) })}
                options={[
                  { value: "1", label: "1" },
                  { value: "2", label: "2" },
                  { value: "3", label: "3" },
                ]}
                className="self-start"
              />
            </Field>
            <Slider id="pb-interrupt" label="Interrupts" value={f.style.interrupt_tendency} onChange={(v) => setStyle({ interrupt_tendency: v })} />
            <Slider id="pb-aggression" label="Aggression" value={f.style.aggression} onChange={(v) => setStyle({ aggression: v })} />
          </div>
        </Section>

        <Section title="Method">
          <Field label="Signature move" htmlFor="pb-move">
            <input id="pb-move" maxLength={120} value={f.signature_move} onChange={(e) => set("signature_move", e.target.value)} className={inputCls} />
          </Field>
          <Field label="How they run the meeting" htmlFor="pb-method">
            <textarea id="pb-method" rows={4} maxLength={2000} value={f.method} onChange={(e) => set("method", e.target.value)} className={cn(inputCls, "h-auto resize-none py-2")} />
          </Field>
          <Field label={`Questions they open with · ${f.question_seeds.length}/20`} htmlFor="pb-seeds">
            <ChipInput id="pb-seeds" label="Opening questions" values={f.question_seeds} onChange={(v) => set("question_seeds", v)} max={20} placeholder="Type a question and press Enter" />
          </Field>
          <Field label={`Dealbreakers · ${f.dealbreakers.length}/10`} htmlFor="pb-deal">
            <ChipInput id="pb-deal" label="Dealbreakers" values={f.dealbreakers} onChange={(v) => set("dealbreakers", v)} max={10} placeholder="Type a dealbreaker and press Enter" />
          </Field>
        </Section>
        {error && <ErrorNote message={error} />}
      </div>
      <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-line px-5 py-3">
        <PillButton label="Cancel" variant="ghost" onClick={onCancel} />
        <PillButton label={saving ? "Saving" : "Save investor"} variant="solid" type="submit" disabled={saving || !f.name.trim()} />
      </footer>
    </form>
  );
}

/**
 * The Areopagus builder (FR-13), a sheet on the right. Create: describe an investor, Gemini drafts
 * the persona (or a keyword draft when it's offline), then the form edits it. Edit: the form opens
 * on a saved custom investor. Persona text is character description; the panel's rules sit above it.
 */
export function PersonaBuilder({
  mode,
  personaId,
  onSaved,
  onClose,
}: {
  mode: "create" | "edit";
  personaId?: string;
  onSaved: (id: string, name: string) => void;
  onClose: () => void;
}) {
  const guard = useAccessGuard();
  const options = useApi<PersonaOptions>("areopagus/options");
  const existing = useApi<VCPersonaSpec>(mode === "edit" && personaId ? `areopagus/${encodeURIComponent(personaId)}` : null);
  const [description, setDescription] = useState("");
  const [draft, setDraft] = useState<(GenerateResult & { n: number }) | null>(null);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  // Whatever opened the builder (New investor, a card's Edit) gets focus back when it closes.
  const [opener] = useState(() => (typeof document === "undefined" ? null : (document.activeElement as HTMLElement | null)));

  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  // A modal sheet: Esc closes it, and Tab / Shift+Tab cycle inside it instead of reaching the page behind.
  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    const items = () => [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => x.getClientRects().length > 0);
    if (!el.contains(document.activeElement)) (items()[0] ?? el).focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close.current();
        return;
      }
      if (e.key !== "Tab") return;
      const list = items();
      const first = list[0];
      const last = list.at(-1);
      const active = document.activeElement;
      if (!first || !last) {
        e.preventDefault();
        el.focus();
      } else if (!el.contains(active)) {
        // Focus fell to <body> (the step it was on was replaced): bring it back in.
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && (active === first || active === el)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    const onFocusIn = (e: FocusEvent) => {
      if (e.target instanceof Node && !el.contains(e.target)) (items()[0] ?? el).focus();
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, []);

  useEffect(() => {
    const el = dialog.current;
    return () => {
      // After the sheet is really gone (not a StrictMode re-run), and only if focus went nowhere else.
      window.setTimeout(() => {
        if (el?.isConnected || !opener?.isConnected) return;
        const active = document.activeElement;
        if (!active || active === document.body) opener.focus();
      });
    };
  }, [opener]);

  const generate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const r = await apiPost<GenerateResult>("areopagus/generate", { description: description.trim() });
      setDraft((d) => ({ ...r, n: (d?.n ?? 0) + 1 }));
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    } finally {
      setGenerating(false);
    }
  };

  const save = async (spec: FormSpec) => {
    setSaving(true);
    setError(null);
    try {
      const saved =
        mode === "edit" && personaId
          ? await apiPut<VCPersonaSpec>(`areopagus/${encodeURIComponent(personaId)}`, spec)
          : await apiPost<VCPersonaSpec>("areopagus", spec);
      onSaved(saved.id, saved.name);
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    } finally {
      setSaving(false);
    }
  };

  const len = description.trim().length;
  const loadError = options.error ?? existing.error;
  let body: ReactNode;
  if (loadError && !(options.data && (mode === "create" || existing.data))) {
    body = <ErrorNote message={errorText(loadError)} onRetry={() => (options.reload(), existing.reload())} className="m-5" />;
  } else if (!options.data || (mode === "edit" && !existing.data)) {
    body = <Loading label="Opening the builder" className="p-5" />;
  } else if (mode === "edit" && existing.data) {
    body = <PersonaForm initial={existing.data} options={options.data} saving={saving} error={error} onSave={(s) => void save(s)} onCancel={onClose} />;
  } else if (draft) {
    body = (
      <PersonaForm
        key={draft.n}
        initial={draft.persona}
        options={options.data}
        saving={saving}
        error={error}
        onSave={(s) => void save(s)}
        onCancel={onClose}
        top={
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-[4px] border border-line px-3 py-2" data-testid="draft-source">
            <span className="text-[11.5px] text-ink-2">
              {draft.source === "gemini" ? "Drafted by Gemini from your description." : "Drafted from keywords; Gemini is offline. Check every field."}
            </span>
            <button type="button" onClick={() => setDraft(null)} className="text-[11.5px] text-ink underline underline-offset-2 hover:text-ember">
              Start over
            </button>
          </div>
        }
      />
    );
  } else {
    body = (
      <form
        className="flex flex-col gap-3 px-5 pb-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (len >= MIN_DESC && len <= MAX_DESC && !generating) void generate();
        }}
      >
        <Field
          label="Describe the investor"
          htmlFor="pb-desc"
          hint={`${len}/${MAX_DESC}. Who they are, what they care about, how they come across. Gemini drafts the persona; you edit it before saving.`}
        >
          <textarea
            id="pb-desc"
            rows={7}
            autoFocus
            value={description}
            maxLength={MAX_DESC}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit();
            }}
            placeholder={EXAMPLE}
            className={cn(inputCls, "h-auto resize-none py-2 leading-snug")}
          />
        </Field>
        {error && <ErrorNote message={error} />}
        <PillButton
          label={generating ? "Drafting" : "Generate"}
          variant="solid"
          type="submit"
          disabled={generating || len < MIN_DESC}
          icon={<Sparkles className="size-3.5" strokeWidth={1.5} />}
          className="self-start"
        />
        {generating && <Loading label="Drafting the persona" />}
      </form>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-[2px]" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={dialog}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={mode === "edit" ? "Edit investor" : "New investor"}
        className="glass flex h-full w-full flex-col bg-surface-solid/95 outline-none sm:max-w-[520px] sm:rounded-l-[22px]"
      >
        <header className="flex shrink-0 items-start justify-between gap-3 px-5 pt-5 pb-4">
          <div className="flex flex-col gap-1">
            <span className="label">{mode === "edit" ? "Edit investor" : "New investor"}</span>
            <h2 className="display text-[30px] leading-none">{mode === "edit" ? existing.data?.name ?? "Investor" : "Build an investor"}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close the builder"
            className="flex size-8 items-center justify-center rounded-full text-ink-2 hover:text-ink"
          >
            <X className="size-4" strokeWidth={1.5} />
          </button>
        </header>
        {body}
      </div>
    </div>
  );
}
