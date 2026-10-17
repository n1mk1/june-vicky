"use client";

import { Canvas, useFrame, useLoader, useThree } from "@react-three/fiber";
import { Suspense, useMemo, useRef } from "react";
import * as THREE from "three";
import { SVGLoader, type SVGResult } from "three/examples/jsm/loaders/SVGLoader.js";
import { palette, useTheme } from "@/lib/use-theme";

/** The geometry comes straight from the brand file, so the 3D mark always matches the logo. */
const LOGO_URL = "/brand/Vicky_Logo.svg";
/** Extrusion depth in SVG units; the letter strokes are about 27 wide. */
const DEPTH = 34;

function buildMark(svg: SVGResult) {
  const shapes = svg.paths.flatMap((p) => p.toShapes());
  const solid = new THREE.ExtrudeGeometry(shapes, { depth: DEPTH, bevelEnabled: false, curveSegments: 16 });
  solid.center();
  solid.rotateX(Math.PI); // SVG y points down; a rotation (not a mirror) keeps the face winding intact
  solid.computeBoundingBox();
  const size = solid.boundingBox!.getSize(new THREE.Vector3());
  const edges = new THREE.EdgesGeometry(solid, 20);

  // One glowing point per unique corner.
  const pos = solid.getAttribute("position");
  const seen = new Set<string>();
  const corners: number[] = [];
  for (let i = 0; i < pos.count; i++) {
    const key = `${pos.getX(i).toFixed(1)},${pos.getY(i).toFixed(1)},${pos.getZ(i).toFixed(1)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    corners.push(pos.getX(i), pos.getY(i), pos.getZ(i));
  }
  const points = new THREE.BufferGeometry();
  points.setAttribute("position", new THREE.Float32BufferAttribute(corners, 3));
  return { solid, edges, points, size };
}

function Mark({ ink, ember, light }: { ink: string; ember: string; light: boolean }) {
  const group = useRef<THREE.Group>(null);
  const svg = useLoader(SVGLoader, LOGO_URL);
  const { solid, edges, points, size } = useMemo(() => buildMark(svg), [svg]);
  const viewport = useThree((s) => s.viewport);
  // Fit the wordmark to the canvas, leaving room for the sway to swing the near end forward.
  const scale = Math.min((viewport.width * 0.6) / size.x, (viewport.height * 0.4) / size.y);

  useFrame((state) => {
    const g = group.current;
    if (!g) return;
    const t = state.clock.elapsedTime;
    const targetY = Math.sin(t * 0.22) * 0.38 + state.pointer.x * 0.28;
    const targetX = -0.16 + Math.sin(t * 0.31) * 0.06 - state.pointer.y * 0.16;
    g.rotation.y += (targetY - g.rotation.y) * 0.05;
    g.rotation.x += (targetX - g.rotation.x) * 0.05;
  });

  return (
    <group ref={group} scale={scale}>
      {/* Echo copies behind the main mark give the layered wireframe depth. */}
      {[DEPTH * 0.85, DEPTH * 1.7].map((z, i) => (
        <lineSegments key={z} geometry={edges} position={[0, 0, -z]}>
          <lineBasicMaterial color={ink} transparent opacity={0.12 - i * 0.05} />
        </lineSegments>
      ))}
      <mesh geometry={solid}>
        <meshBasicMaterial color={ink} transparent opacity={light ? 0.05 : 0.025} depthWrite={false} />
      </mesh>
      <lineSegments geometry={edges}>
        <lineBasicMaterial color={ink} transparent opacity={light ? 0.7 : 0.55} />
      </lineSegments>
      <points geometry={points}>
        <pointsMaterial color={ember} size={0.055} sizeAttenuation transparent opacity={0.9} />
      </points>
    </group>
  );
}

export default function VMark3D() {
  const { theme } = useTheme();
  const c = palette[theme];
  const reduced = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return (
    <Canvas
      dpr={[1, 1.5]}
      frameloop={reduced ? "demand" : "always"}
      camera={{ position: [0, 0, 7.5], fov: 35 }}
      gl={{ antialias: true, alpha: true }}
      aria-hidden
    >
      <Suspense fallback={null}>
        <Mark ink={c.ink} ember={c.ember} light={theme === "light"} />
      </Suspense>
    </Canvas>
  );
}
