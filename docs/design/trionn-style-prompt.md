# Style-transfer prompt — "Trionn-style" cinematic studio site

> Reference studied: https://trionn.com (home, services, menu, footer — Oct 2026).
> This prompt captures the **look, feel and interaction concept** only. Use your own brand, logo, copy, imagery and 3D assets — do not reuse Trionn's logo, text, photos or models.
>
> Fill in the `[BRACKETS]` before pasting into Claude / v0 / Lovable / Cursor.

---

## THE PROMPT (copy everything below)

Build a website for **[BRAND NAME]**, a **[what the business is]**, with the visual language of a high-end, award-site-style creative studio. The site should feel **cinematic, monochrome, engineered and tactile**: near-black space scenes with glowing 3D line-art, alternating with soft grey "gallery paper" sections, oversized tight-tracked grotesk headlines, tiny mono-spaced technical labels, hairline grid lines with "+" crosshair markers, and scroll-driven 3D storytelling built around the brand's **[MONOGRAM / LOGO MARK]**.

### 1. Core concept

- **One hero object carries the story.** The brand monogram exists as a 3D object that changes across the page: a glowing wireframe in the hero, a solid glowing extrusion at the first scroll transition, then **carved into a rough stone slab** in the services section. Every big section is a "scene" in which that object appears.
- **Dark ↔ light rhythm.** Sections alternate: dark hero → dark statement → light facts → light work → dark services (smoke/clouds) → light testimonials → light gallery → dark footer. Transitions between them are cinematic (curtain/stripe wipes, gradient fades), never hard cuts.
- **Quiet UI, loud type.** Chrome is minimal and small (12–13px). Headlines are huge, tightly tracked and calm. Nothing is colorful except one ember-orange accent used in light streaks and tiny icons.
- **Technical, blueprint feel.** Thin 1px lines, "+" marks where grid lines cross, corner-bracket frames, uppercase mono micro-labels, numeric counters, a live local-time clock.

### 2. Design tokens

```css
:root {
  /* Dark scenes */
  --bg-deep: #040508;        /* page / space background */
  --bg-hero: #0C0C0C;        /* hero section */
  --ink-on-dark: #D8D8D8;    /* primary text on dark */
  --ink-on-dark-dim: rgba(216,216,216,.5);
  --line-on-dark: rgba(255,255,255,.18);   /* hairlines, glass borders */

  /* Light scenes */
  --paper: #C8C8C8;          /* preloader + panel grey */
  --paper-2: #D8D8D8;
  --ink-on-light: #434343;   /* body text on light */
  --ink-strong: #111111;     /* big headlines on light */
  --grad-light-up: linear-gradient(0deg, #FFFFFF 0%, #D2D2D2 100%);
  --grad-light-down: linear-gradient(0deg, #C3C3C3 0%, #FFFFFF 100%);

  /* Accent — use sparingly (light streaks, tiny icons, 3D glow) */
  --ember: #D9432B;
  --ember-glow: #FF7A3D;

  /* Motion */
  --ease-soft: cubic-bezier(.22, 1, .36, 1);
  --dur-fast: .35s;
  --dur-med: .8s;
  --dur-slow: 1.4s;
}
```

**Fonts (3-family system):**

| Role | Reference font | Free substitute | Usage |
|---|---|---|---|
| Display / headings / buttons | Familjen Grotesk (400–500) | same (Google Fonts) | all headlines, CTA pills |
| Body / UI | Neue Haas Grotesk Display | Inter Tight or Hanken Grotesk | paragraphs, nav, captions |
| Technical labels | Martian Mono | same (Google Fonts) | uppercase micro-labels, link CTAs, counters |

**Type scale (desktop, scale fluidly with `clamp`):**

- **Hero H1:** `clamp(48px, 6.6vw, 112px)`, weight 400, letter-spacing **-0.06em**, line-height **0.9**, sentence case, 2 short lines, left-aligned, top-left of the viewport.
- **Statement H2:** same size as H1, -0.06em, line-height 0.95. A full paragraph set as a headline (3–4 lines), first line indented by ~1 word width.
- **Stacked uppercase list (services):** `clamp(56px, 9vw, 150px)`, uppercase, letter-spacing **-0.08em**, line-height **0.8**, centered, one discipline per line.
- **H3 / card titles:** 21px, -0.04em, line-height 1.
- **Body:** 13–14px, normal tracking, `--ink-on-light` or `--ink-on-dark`, max ~32ch, often in a narrow right-hand column.
- **Mono labels:** 10.5px Martian Mono, UPPERCASE, letter-spacing -0.06em. Used for: section eyebrows ("OUR SERVICES"), link CTAs ("EXPLORE PROJECT →"), counters, the clock.

### 3. Components & signature details

- **Header (fixed, transparent):** logo mark + wordmark left. Right side: a small round **sound toggle** (muted-speaker icon), a **filled pill** "LET'S TALK" (white bg, black text) and an **outline pill** "MENU ≡" (1px border). Pills: Familjen 12.8px uppercase, padding `4.5px 12px 6px`, fully rounded. Header colors invert automatically on light sections (mix-blend-mode: difference, or per-section theme switching).
- **Button hover = letter roll:** every pill/link holds its label twice, stacked; on hover the first copy slides up and the second slides in from below, staggered per letter (20ms per char, `--ease-soft`).
- **Text links:** mono uppercase label + "→", with a 1px underline running the full width of the link; on hover the underline wipes out to the right and back in from the left, and the arrow nudges 4px.
- **Menu:** clicking MENU slides in an off-canvas panel from the right (~40% width, white, top-to-bottom with large rounded inset). Contents: 4 large nav links (Familjen ~32px, stacked), a small outline chip linking to a brand-story page, then "Business enquiry" (email, phone) and "Social" (2×2 grid) in small text at the bottom. MENU label changes to "MENU ×".
- **Crosshair grid:** thin 1px vertical/horizontal guide lines on many sections, with small "+" marks at intersections and at frame corners. Project lists sit in columns separated by full-height hairlines.
- **Corner-bracket frames:** square frames with "+" marks just outside each corner (preloader, stat badge, featured media).
- **Stat badge (hero, bottom-right):** a small 2-cell glass card with 1px border: left cell a line-icon globe + "EST. [YEAR]"; right cell "[N]+ YEARS [SHORT CLAIM]". Below it a 3-line positioning sentence in body text.
- **Custom cursor:** a small dot/ring that grows into a labelled circle ("DRAG", "VIEW", "PLAY") over interactive media.
- **Sound design (optional, off by default):** subtle UI ticks on hover and an ambient drone; a tiny footer hint telling visitors sound is available.

### 4. Page structure (homepage, in order)

1. **Preloader** — flat `--paper` grey screen. A centered square frame with "+" corners; a thin dark progress line draws along the frame's top edge; the monogram assembles inside from line fragments (line-draw/glitch slices). Under the frame, a 3-word tagline in tiny caps separated by "·" ("[WORD] · [WORD] · [WORD]"). Bottom center: a rolling 3-digit counter 000 → 100 (each digit is a vertical strip of 0–9 that rolls). On complete, the frame scales up and the page wipes to the dark hero.

2. **Hero (dark, full viewport)** — `--bg-hero`. Center-right: a big **3D wireframe extrusion of the monogram**, slowly rotating, edges in faint grey with glowing vertices. Background: sparse **light streaks / shooting lines** (thin white and ember-orange) drifting diagonally, plus a large soft white-blue glossy shape in the bottom-right corner for depth. Top-left: the 2-line H1. Bottom-right: stat badge + positioning line. Bottom-center: a playful interaction hint in tiny caps with small ember icons, e.g. "HOLD TO [💥] [VERB] · [VERB] [⚡] THE LINES" (your own wording) — holding the mouse makes the streaks explode outward; hovering lines makes them react. Bottom-left: a small circular "+" button.

3. **Statement / About (dark)** — Eyebrow "ABOUT" top-left in mono. A large headline-paragraph describing the brand, revealed **word by word** on scroll (words go from 15% opacity to 100% as they cross the viewport center), with a tiny inline icon replacing one character. Below: a two-column row — left, a 3-line uppercase mono manifesto; right, a 3-line mission sentence + a "MORE ABOUT US →" underlined mono link. The hero's 3D object and streaks continue faintly behind.

4. **Monogram transition (dark, pinned)** — pin the section; the wireframe monogram solidifies piece by piece into a **glowing ember/orange extruded stroke** while three "+" crosshairs sit on a horizontal guide line across the top third. Ends with a **stripe/curtain wipe** (horizontal black bands sliding off) into the light section.

5. **Key facts (light, `--grad-light-down`)** — Heading "[Key facts]" that resolves from **heavy blur to sharp** letter by letter. Then a 3-card row with equal heights and small radius (~6px):
   - Card A: tall portrait photo (bold editorial/surreal character image), overlaid at the bottom with a small badge/logo, a 2-line caption and a big number "[50]+" with a superscript plus.
   - Card B: a light card holding a **large white circle** with "[1.5K]+" centered, caption below.
   - Card C: a dark photo card, caption + big number "[20]+".
   Numbers count up when visible. Below: eyebrow "OUR BUSINESS PARTNERS" and a single row of 5 greyscale partner logos separated by thin vertical lines.

6. **Featured work (light, horizontal scroll)** — Pin the section and translate a horizontal track as the user scrolls vertically. The left edge carries a huge headline that slides out with motion blur ("[Selected work / innovations]"). Columns are divided by full-height hairlines; project cards sit at **staggered vertical positions** (some high, some low). Each card: a 16:10 rounded image with an in-image UI mockup of the project, then title (H3), a one-line description, and an underlined mono "EXPLORE PROJECT →" link on the right. Images scale 1.0 → 1.05 on hover and the cursor becomes "VIEW". The track ends on a centered panel with a one-line invitation to see more + "VIEW ALL PROJECTS →".

7. **Services (pinned, light → dark)** — Starts on flat `--paper` grey: eyebrow "OUR SERVICES", then the **stacked uppercase discipline list** ([A.I.] / [DESIGN] / [DEVELOPMENT] / [BRANDING]) in `--ink-strong`, footer row with a mono tagline left and "VIEW SERVICES →" right. As you scroll: the background fades into **dark volumetric smoke/clouds**, the text turns light, and a **rough stone slab** drops in, tumbles and rotates until it faces the camera square-on behind the text. The text fades away and the **monogram gets carved into the stone** stroke by stroke. Then the individual services fly in **orbiting around the slab** — each one a small line-art 3D icon (concentric arcs, stacked bars, rings), a 2-line title and a 2–3 line description, placed at different depths with parallax.

8. **Testimonials (light, `--grad-light-up`)** — Top row: big H2 "[Client stories]" left, short 3-line intro right, full-width hairline with a centered "+" below. Body: left column a vertical list of client names as small grey caps tabs (active one dark with "→"); right column a large quote (~22px, line-height 1.2), then avatar (square, small radius) + name + role, and a "▷ LISTEN TO [THEM]" mono button that plays a voice clip. Bottom-left: two square outline arrow buttons (← →) joined together. Below: an underlined "BECOME A CLIENT →" link. Quotes crossfade with a slight upward slide.

9. **"Design in motion" gallery (light grey)** — Huge 2-line headline split left/right with a tiny mono caption between the lines. Below, a **curved 3D carousel**: ~10 portrait-ish shots arranged along an arc (cylinder) that rotates as you scroll, with thin curved guide lines sweeping across the background. Small caption bottom-left, "VIEW ON [PLATFORM] →" bottom-right. As you scroll past, the cards fly apart toward the edges and the headline splits horizontally.

10. **Footer CTA (dark)** — Transition in via **horizontal black bands wiping across** the gallery. Dark smoky background. Top row: mono eyebrow "[SHORT INVITATION]" left, live clock "[TZ] → HH:MM" right. Big 2-line H2 "[Your closing CTA question]" left; right, two stacked underlined mono CTAs ("DISCUSS YOUR PROJECT →", "BOOK A 30-MINUTE CALL →"). Info grid: © line, "SOUND ON" hint, Business enquiry (E:/P:), Social (2×2). At the very bottom, a **giant full-width wordmark** of the brand built from horizontal scanlines (sliced into thin stripes), which glow/shift when hovered.

### 5. Inner pages (same system)

- **Services page:** dark. Hero = a ring of floating 3D line-art objects orbiting on a thin elliptical path around a centered 3-line headline about your disciplines that **unblurs word by word**. Two CTAs under it. Then a giant one-line "[BRANDING] + [A.I.] + [DESIGN]" marquee with "+" separators and 3D objects passing in front of and behind the letters, and a mono tagline under it. Then a detailed block for each service.
- **Work page:** filterable grid/list of projects using the same card style and hairline columns.
- **About / Story page:** a long-form scroll story in the statement style, with team portraits in the same editorial photo treatment.
- **Contact page:** dark, a large form with underline-only inputs, mono labels and the pill submit button.
- Every route runs the short **preloader** (frame + counter) as its page transition.

### 6. Motion spec

- **Smooth scroll:** Lenis (`lerp: 0.08`), synced with GSAP ScrollTrigger.
- **Default ease** `cubic-bezier(.22,1,.36,1)`. Text reveals 0.8–1.2s; UI hovers 0.35s.
- **Reveal vocabulary (use only these):**
  1. **Blur-to-sharp per letter** (filter: blur(12px) → 0, opacity .2 → 1, stagger 25ms) for section titles.
  2. **Word-by-word opacity scrub** tied to scroll for statement paragraphs.
  3. **Line mask rise** (each line slides up 100% out of an overflow-hidden wrapper) for H1s.
  4. **Rolling digits** for counters and the clock.
  5. **Stripe/curtain wipes** (6–10 horizontal bands with staggered translateX) between dark and light scenes.
- **Pinned scenes:** the monogram transition, the horizontal work track, the services stone sequence and the gallery arc are all pinned, with scrub 1.
- **Hover:** letter-roll on pills, underline wipe on links, image scale on cards, parallax tilt (max 6°) on 3D objects following the cursor.
- **Respect `prefers-reduced-motion`:** turn off scrub/pin animations, show static end states, keep fades under 200ms, disable sound.

### 7. 3D & imagery direction

- **Tech:** React Three Fiber + drei. One `<Canvas>` per scene, lazy-mounted when near the viewport, DPR capped at 1.5, and a static fallback image on low-end/mobile devices.
- **Monogram model:** extrude your SVG mark (depth ~0.3). Materials: (a) wireframe `EdgesGeometry` lines at 30% opacity with additive point sprites at the vertices; (b) emissive ember gradient for the solid state; (c) a displacement-mapped rough stone slab with the mark as a normal/displacement "engraving" mask animated by a uniform.
- **Streaks:** instanced thin quads with an additive gradient (white → transparent; ~10% ember), moving diagonally; spawn bursts on pointer hold.
- **Atmosphere:** dark volumetric clouds/smoke (a pre-rendered video loop or a noise shader) at 40–60% brightness.
- **Photography:** bold, editorial, slightly surreal (high-contrast portraits, architecture, dramatic lighting). Greyscale partner logos. Project thumbnails are polished UI mockups.

### 8. Layout & responsive rules

- 12-column grid, 24px side padding on desktop and 16px on mobile, with lots of negative space. Headlines hug the top-left; supporting copy sits in narrow right-hand columns.
- **Mobile:** the horizontal work track becomes a vertical stack; pinned 3D sequences become short autoplay loops or static frames; the stacked services list scales down to `clamp` minimums; the menu panel goes full-screen; the stat badge moves below the H1.
- Keep the page fast. Preload fonts. Load 3D and video after first paint. Target LCP < 2.5s with the hero H1 as the LCP element (render it in HTML, not canvas).

### 9. Tech stack

Next.js (App Router) + TypeScript + Tailwind CSS v4 · GSAP + ScrollTrigger + SplitText · Lenis · React Three Fiber + drei · next/font for Familjen Grotesk, Martian Mono and the body grotesk · Howler.js for optional sound.

### 10. Content to supply

`[BRAND NAME]`, `[MONOGRAM SVG]`, hero headline (2 short lines), statement paragraph, manifesto (3 lines), mission line, 3 key stats with captions, 5 partner logos, 4–6 projects (image, title, one-liner), 4 services (title + 2-line description + icon idea), 4–5 testimonials (quote, name, role, photo, optional audio), 8–12 gallery shots, contact email/phone, socials, timezone.

---

## Quick version (for tools with short prompt limits)

> Build a cinematic, monochrome creative-studio website for [BRAND]. Near-black (#040508) 3D scenes alternate with soft grey gradient "paper" sections (#C8C8C8 → #FFFFFF). Typography: Familjen Grotesk headlines (huge, -0.06em tracking, 0.9 line-height; the services list is uppercase at -0.08em), Inter Tight body at 13px, Martian Mono 10px uppercase micro-labels. A single ember accent (#D9432B). Blueprint details: 1px hairlines, "+" crosshairs at intersections, corner-bracket frames, rolling digit counters, a live clock. Fixed header with a sound toggle, a white "LET'S TALK" pill and an outline "MENU" pill (letter-roll hover) that opens a right-side white panel. The brand monogram is the recurring 3D hero object: a glowing wireframe with shooting light streaks in the hero → a solid ember extrusion → carved into a rotating stone slab in dark smoke for services, with service cards orbiting it. Sections: preloader (frame + 000→100 counter) → hero → word-by-word statement → blur-in "Key facts" stat cards + partner logos → pinned horizontal-scroll project track with hairline columns → pinned services stone sequence → testimonials with tabbed client list and audio "listen" button → curved 3D carousel gallery → dark footer CTA with a giant scanline wordmark. Use Lenis smooth scroll, GSAP ScrollTrigger pins, blur-to-sharp letter reveals, stripe curtain wipes between dark and light scenes, and React Three Fiber. Fully respect prefers-reduced-motion.
