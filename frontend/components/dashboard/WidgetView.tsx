"use client";

import { kindOf, type WidgetProps } from "./registry";

/** Renders one dashboard widget through the registry (by status, then template). */
export function WidgetView(props: WidgetProps) {
  const Kind = kindOf(props.widget).component;
  return <Kind {...props} />;
}
