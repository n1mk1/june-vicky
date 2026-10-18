"use client";

import { Environment, Lightformer } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { palette, useTheme } from "@/lib/use-theme";

/**
 * The landing's hero object: the V from the VICKY wordmark, rebuilt as two extruded arms on
 * stepped depths (the right arm sits back, its top sliced by the brand's "/" knife cut), in dark
 * glossy glass with an ember core. It spins slowly; the pointer tilts it.
 *
 * Arm outlines come from the wordmark's V (0,0 30,0 62,94.7 94,0 124,0 76,142 48,142): each arm's
 * inner edge is extended to the baseline so the two overlap into the V's foot.
 */
const LEFT_ARM: [number, number][] = [
  [0, 0],
  [30, 0],
  [78, 142],
  [48, 142],
];
const RIGHT_ARM: [number, number][] = [
  [99, 15], // knife cut: the top is sliced along a "/"
  [124, 0],
  [76, 142],
  [46, 142],
  [89, 15],
];
const DEPTH = 30;
const STEP = DEPTH + 10; // the right arm sits behind the left, with a gap between them for the ember
const GAP_Z = 0; // that gap sits at the pair's centre once it is centred

function shapeOf(points: [number, number][]) {
  const s = new THREE.Shape();
  points.forEach(([x, y], i) => (i === 0 ? s.moveTo(x, -y) : s.lineTo(x, -y)));
  s.closePath();
  return s;
}

function useArms() {
  return useMemo(() => {
    const opts = { depth: DEPTH, bevelEnabled: true, bevelThickness: 1.6, bevelSize: 1.2, bevelSegments: 3, curveSegments: 1 };
    const left = new THREE.ExtrudeGeometry(shapeOf(LEFT_ARM), opts);
    const right = new THREE.ExtrudeGeometry(shapeOf(RIGHT_ARM), opts);
    right.translate(0, 0, -STEP);
    // Centre the pair on the V's own box so it spins about its middle.
    const box = new THREE.Box3().setFromBufferAttribute(left.getAttribute("position") as THREE.BufferAttribute);
    box.union(new THREE.Box3().setFromBufferAttribute(right.getAttribute("position") as THREE.BufferAttribute));
    const c = box.getCenter(new THREE.Vector3());
    left.translate(-c.x, -c.y, -c.z);
    right.translate(-c.x, -c.y, -c.z);
    const size = box.getSize(new THREE.Vector3());
    return {
      left,
      right,
      leftEdges: new THREE.EdgesGeometry(left, 25),
      rightEdges: new THREE.EdgesGeometry(right, 25),
      size,
    };
  }, []);
}

/** A soft radial sprite for the ember glow (no post-processing needed). */
function useGlowTexture() {
  return useMemo(() => {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const g = c.getContext("2d")!;
    const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grad.addColorStop(0, "rgba(255,170,110,1)");
    grad.addColorStop(0.25, "rgba(255,110,60,0.55)");
    grad.addColorStop(1, "rgba(255,80,40,0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, 128, 128);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }, []);
}

function Orbits({ color }: { color: string }) {
  const group = useRef<THREE.Group>(null);
  const rings = useMemo(
    () =>
      [
        { rx: 4.6, ry: 1.1, tilt: [1.25, 0.2, -0.35] as const, opacity: 0.22 },
        { rx: 6.2, ry: 1.6, tilt: [1.1, -0.4, 0.5] as const, opacity: 0.14 },
        { rx: 3.4, ry: 0.7, tilt: [1.45, 0.6, 0.1] as const, opacity: 0.12 },
      ].map((r) => {
        const pts = new THREE.EllipseCurve(0, 0, r.rx, r.ry, 0, Math.PI * 2).getPoints(160);
        const geo = new THREE.BufferGeometry().setFromPoints(pts.map((p) => new THREE.Vector3(p.x, p.y, 0)));
        return { ...r, geo };
      }),
    [],
  );
  useFrame((_, dt) => {
    if (group.current) group.current.rotation.y += dt * 0.04;
  });
  return (
    <group ref={group}>
      {rings.map((r, i) => (
        <lineLoop key={i} geometry={r.geo} rotation={[r.tilt[0], r.tilt[1], r.tilt[2]]}>
          <lineBasicMaterial color={color} transparent opacity={r.opacity} />
        </lineLoop>
      ))}
    </group>
  );
}

function Mark({ light, reduced }: { light: boolean; reduced: boolean }) {
  const spin = useRef<THREE.Group>(null);
  const tilt = useRef<THREE.Group>(null);
  const glow = useRef<THREE.Sprite>(null);
  const ember = useRef<THREE.PointLight>(null);
  const { left, right, leftEdges, rightEdges, size } = useArms();
  const glowTex = useGlowTexture();
  const viewport = useThree((s) => s.viewport);
  const c = palette[light ? "light" : "dark"];
  const scale = Math.min((viewport.height * 0.52) / size.y, (viewport.width * 0.42) / size.x);
  const grow = useRef(0);
  const invalidate = useThree((s) => s.invalidate);

  // Reduced motion renders on demand: draw again once mounted (and after a resize) so the frame
  // callback below has applied the finished pose.
  useEffect(() => {
    if (!reduced) return;
    const id = requestAnimationFrame(() => invalidate(2));
    return () => cancelAnimationFrame(id);
  }, [reduced, invalidate, scale, light]);

  useFrame((state, dt) => {
    const t = state.clock.elapsedTime;
    // Reduced motion: no entrance and no spin, just a finished three-quarter view.
    grow.current = reduced ? 1 : Math.min(1, grow.current + dt * 0.8);
    const k = 1 - Math.pow(1 - grow.current, 3); // ease-out entrance
    if (spin.current) {
      if (reduced) spin.current.rotation.y = -0.55;
      else spin.current.rotation.y += dt * 0.42;
      spin.current.scale.setScalar(scale * (0.7 + 0.3 * k));
    }
    if (tilt.current) {
      const tx = -0.12 + (reduced ? 0 : Math.sin(t * 0.35) * 0.05 - state.pointer.y * 0.18);
      const tz = reduced ? 0.03 : Math.sin(t * 0.27) * 0.04 + state.pointer.x * 0.08;
      tilt.current.rotation.x += (tx - tilt.current.rotation.x) * (reduced ? 1 : 0.05);
      tilt.current.rotation.z += (tz - tilt.current.rotation.z) * (reduced ? 1 : 0.05);
    }
    // The core breathes, brightest when the arms face the camera.
    const facing = spin.current ? Math.abs(Math.cos(spin.current.rotation.y)) : 1;
    const pulse = (reduced ? 0.9 : 0.75 + 0.25 * Math.sin(t * 1.4)) * (0.45 + 0.55 * facing) * k;
    if (glow.current) (glow.current.material as THREE.SpriteMaterial).opacity = (light ? 0.4 : 0.62) * pulse;
    if (ember.current) ember.current.intensity = 26 * pulse;
  });

  const body = light ? "#d4d5d8" : "#252833";
  return (
    // The first frame is already sized and posed, before any frame callback runs.
    <group ref={tilt} rotation={[-0.12, 0, reduced ? 0.03 : 0]}>
      <group ref={spin} scale={scale * (reduced ? 1 : 0.7)} rotation={[0, reduced ? -0.55 : 0, 0]}>
        {[left, right].map((geo, i) => (
          <mesh key={i} geometry={geo}>
            <meshPhysicalMaterial
              color={body}
              metalness={light ? 0.4 : 0.85}
              roughness={light ? 0.25 : 0.14}
              clearcoat={1}
              clearcoatRoughness={0.08}
              envMapIntensity={light ? 1.1 : 2.4}
            />
          </mesh>
        ))}
        {[leftEdges, rightEdges].map((geo, i) => (
          <lineSegments key={i} geometry={geo}>
            <lineBasicMaterial color={light ? c.ink : "#ffffff"} transparent opacity={light ? 0.4 : 0.3} />
          </lineSegments>
        ))}
        {/* Ember slit in the gap between the stepped arms: seen edge-on as the V turns. */}
        <mesh position={[0, -46, -GAP_Z]}>
          <boxGeometry args={[14, 50, 4]} />
          <meshBasicMaterial color={c.ember} toneMapped={false} />
        </mesh>
        {/* Ember core: a light in the crease and a glow that leaks through the glass. */}
        <pointLight ref={ember} position={[0, -40, -GAP_Z]} color={c.ember} distance={160} decay={1.4} />
        <sprite ref={glow} position={[0, -42, -GAP_Z]} scale={[78, 78, 1]} renderOrder={10}>
          <spriteMaterial map={glowTex} transparent depthWrite={false} depthTest={false} blending={THREE.AdditiveBlending} />
        </sprite>
      </group>
    </group>
  );
}

export default function SpinningV() {
  const { theme } = useTheme();
  const light = theme === "light";
  const reduced = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return (
    <Canvas
      dpr={[1, 1.75]}
      frameloop={reduced ? "demand" : "always"}
      camera={{ position: [0, 0, 9], fov: 34 }}
      gl={{ antialias: true, alpha: true }}
      aria-hidden
    >
      <ambientLight intensity={light ? 0.6 : 0.2} />
      <directionalLight position={[4, 6, 5]} intensity={light ? 1.4 : 1.1} />
      <directionalLight position={[-5, -2, 3]} intensity={light ? 0.4 : 0.35} color={palette.dark.ember} />
      {/* A local light rig for reflections: long softboxes read as the streaks along the glass edges. */}
      <Environment resolution={256} frames={1}>
        <Lightformer form="rect" intensity={light ? 3 : 6} position={[0, 6, -4]} scale={[16, 1.2, 1]} />
        <Lightformer form="rect" intensity={light ? 2 : 4} position={[-7, 1, 2]} rotation-y={Math.PI / 2} scale={[12, 0.8, 1]} />
        <Lightformer form="rect" intensity={light ? 2 : 5} position={[7, -1, 1]} rotation-y={-Math.PI / 2} scale={[12, 0.6, 1]} />
        <Lightformer form="rect" intensity={light ? 1.5 : 3} position={[0, -2, 8]} scale={[10, 0.4, 1]} />
        <Lightformer form="ring" color={palette.dark.ember} intensity={light ? 1 : 3} position={[0, -4, 6]} scale={4} />
      </Environment>
      <Orbits color={light ? palette.light.ink : "#ffffff"} />
      <Mark light={light} reduced={reduced} />
    </Canvas>
  );
}
