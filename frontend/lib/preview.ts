/**
 * Offline preview for the Simulation stage's slide view and ledger, shown until deck upload lands.
 * Illustrative only: no company, no customers and no computed figures. The UI labels
 * it "Preview" wherever it appears.
 */

import type { FeedItem } from "@/components/prep/ChatFeed";
import type { ClaimStatus } from "./types";

export interface PreviewSlide {
  n: number;
  title: string;
  headline: string;
  body: string;
  claim?: { text: string; status: ClaimStatus; truth: string };
}

export const PREVIEW_DECK: PreviewSlide[] = [
  { n: 1, title: "Cover", headline: "Your company", body: "The round you're raising, in one line." },
  {
    n: 2,
    title: "Traction",
    headline: "Growth",
    body: "The growth rate you say out loud.",
    claim: { text: "Growth rate", status: "contradicts", truth: "checked against the rate your data supports" },
  },
  {
    n: 3,
    title: "Unit economics",
    headline: "Gross margin",
    body: "Margin as booked, and once support is counted.",
    claim: { text: "Gross margin", status: "matches", truth: "matches your income statement" },
  },
  {
    n: 4,
    title: "Customers",
    headline: "Pipeline",
    body: "A deal that isn't signed yet.",
    claim: { text: "Expansion deal", status: "forecast_as_fact", truth: "a forecast stated as fact" },
  },
  {
    n: 5,
    title: "The ask",
    headline: "Runway",
    body: "How long the round lasts.",
    claim: { text: "Runway", status: "unsupported", truth: "not supported by cash and burn on file" },
  },
];

export const PREVIEW_FEED: FeedItem[] = [
  { id: "p1", kind: "founder", text: "Preview: your live transcript appears here as you present." },
  {
    id: "p2",
    kind: "vc",
    name: "Panel",
    glyph: "slash",
    text: "Preview: when a claim contradicts your data, one investor may interrupt, at most once per slide.",
  },
  {
    id: "p3",
    kind: "slide",
    slide: 2,
    title: "Traction",
    note: "Preview: slide notes suggest a rewording that matches the figure your data supports.",
  },
];

export const PREVIEW_LEDGER: Record<ClaimStatus, number | null> = {
  matches: null,
  contradicts: null,
  unsupported: null,
  forecast_as_fact: null,
};
