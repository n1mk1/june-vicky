"use client";

import dynamic from "next/dynamic";

// WebGL scenes only run in the browser and load after first paint.
export const OrbScene = dynamic(() => import("./ReadinessOrb"), { ssr: false });
