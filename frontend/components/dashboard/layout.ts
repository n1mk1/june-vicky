/**
 * The dashboard's top row, declared as data. Each column spans part of the 12-column grid and
 * stacks modules (see `modules.tsx`): `role:<role>` is a stored widget with that role, anything
 * else is a panel. `grow` shares the column's height (0 = natural height). Every widget not
 * placed here flows into the row below, so all of them stay on one screen above the chat.
 */
export interface HeroSlot {
  module: string;
  title: string;
  grow?: number;
}

export interface HeroColumn {
  span: 3 | 4 | 6;
  slots: HeroSlot[];
}

export const HERO: HeroColumn[] = [
  {
    span: 3,
    slots: [
      { module: "readiness", title: "Pitch readiness", grow: 0 },
      { module: "role:margin_ring", title: "Gross margin", grow: 1 },
    ],
  },
  { span: 3, slots: [{ module: "role:headline_kpi", title: "Headline" }] },
  { span: 3, slots: [{ module: "role:trend", title: "Trend" }] },
  { span: 3, slots: [{ module: "attack_list", title: "What they'll ask first" }] },
];

/** Widget roles the top row shows, so the row below doesn't repeat them. */
export const HERO_ROLES = new Set(
  HERO.flatMap((c) => c.slots.map((s) => s.module)).filter((m) => m.startsWith("role:")).map((m) => m.slice(5)),
);
