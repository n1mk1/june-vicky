"use client";

import { useEffect, useRef } from "react";
import { palette } from "@/lib/use-theme";

interface Streak {
  x: number;
  y: number;
  len: number;
  speed: number;
  alpha: number;
  ember: boolean;
  vx: number;
  vy: number;
}

const ANGLE = (-38 * Math.PI) / 180;
const DIR = { x: Math.cos(ANGLE), y: -Math.sin(ANGLE) };

/** Thin light streaks drifting diagonally. Holding the pointer down scatters them. */
export function LightStreaks({ count = 46, className }: { count?: number; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0;
    let h = 0;
    let raf = 0;
    let hold = false;
    const pointer = { x: -9999, y: -9999 };

    const spawn = (anywhere: boolean): Streak => ({
      x: anywhere ? Math.random() * w : Math.random() * w * 1.2 - w * 0.2,
      y: anywhere ? Math.random() * h : -20 - Math.random() * h * 0.3,
      len: 40 + Math.random() * 160,
      speed: 0.4 + Math.random() * 1.4,
      alpha: 0.15 + Math.random() * 0.55,
      ember: Math.random() < 0.14,
      vx: 0,
      vy: 0,
    });

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const streaks = Array.from({ length: count }, () => spawn(true));

    const draw = () => {
      const colors = palette[document.documentElement.dataset.theme === "light" ? "light" : "dark"];
      ctx.clearRect(0, 0, w, h);
      for (const s of streaks) {
        const boost = hold ? 7 : 1;
        // Push streaks away from a held pointer, then let them settle back.
        if (hold) {
          const dx = s.x - pointer.x;
          const dy = s.y - pointer.y;
          const d2 = dx * dx + dy * dy + 400;
          s.vx += (dx / d2) * 60;
          s.vy += (dy / d2) * 60;
        }
        s.vx *= 0.94;
        s.vy *= 0.94;
        s.x += DIR.x * s.speed * boost + s.vx;
        s.y += DIR.y * s.speed * boost + s.vy;

        const tx = s.x - DIR.x * s.len;
        const ty = s.y - DIR.y * s.len;
        const grad = ctx.createLinearGradient(s.x, s.y, tx, ty);
        const c = s.ember ? colors.ember : colors.ink;
        grad.addColorStop(0, c);
        grad.addColorStop(1, "transparent");
        ctx.globalAlpha = s.alpha * (document.documentElement.dataset.theme === "light" ? 0.55 : 1);
        ctx.strokeStyle = grad;
        ctx.lineWidth = s.ember ? 1.2 : 0.8;
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(tx, ty);
        ctx.stroke();

        if (s.x > w + 200 || s.y > h + 200 || s.x < -400 || s.y < -400) Object.assign(s, spawn(false));
      }
      ctx.globalAlpha = 1;
      if (!reduced) raf = requestAnimationFrame(draw);
    };
    draw();

    const down = (e: PointerEvent) => {
      if ((e.target as HTMLElement).closest("a,button,input,textarea")) return;
      hold = true;
      pointer.x = e.clientX - canvas.getBoundingClientRect().left;
      pointer.y = e.clientY - canvas.getBoundingClientRect().top;
    };
    const up = () => (hold = false);
    window.addEventListener("resize", resize);
    window.addEventListener("pointerdown", down);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
  }, [count]);

  return <canvas ref={ref} aria-hidden className={className ?? "pointer-events-none absolute inset-0 size-full"} />;
}
