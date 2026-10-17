"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { MARK_POLYS } from "@/components/ui/VickyMark";
import { palette, useTheme } from "@/lib/use-theme";

function buildMark() {
  const shapes = MARK_POLYS.map((poly) => new THREE.Shape(poly.map(([x, y]) => new THREE.Vector2(x - 12, 12 - y))));
  const solid = new THREE.ExtrudeGeometry(shapes, { depth: 3.2, bevelEnabled: false });
  solid.center();
  const edges = new THREE.EdgesGeometry(solid, 20);

  // One glowing point per unique corner.
  const pos = solid.getAttribute("position");
  const seen = new Set<string>();
  const corners: number[] = [];
  for (let i = 0; i < pos.count; i++) {
    const key = `${pos.getX(i).toFixed(2)},${pos.getY(i).toFixed(2)},${pos.getZ(i).toFixed(2)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    corners.push(pos.getX(i), pos.getY(i), pos.getZ(i));
  }
  const points = new THREE.BufferGeometry();
  points.setAttribute("position", new THREE.Float32BufferAttribute(corners, 3));
  return { solid, edges, points };
}

function Mark({ ink, ember, light }: { ink: string; ember: string; light: boolean }) {
  const group = useRef<THREE.Group>(null);
  const { solid, edges, points } = useMemo(() => buildMark(), []);

  useFrame((state) => {
    const g = group.current;
    if (!g) return;
    const t = state.clock.elapsedTime;
    const targetY = Math.sin(t * 0.22) * 0.55 + state.pointer.x * 0.35;
    const targetX = -0.18 + Math.sin(t * 0.31) * 0.06 - state.pointer.y * 0.18;
    g.rotation.y += (targetY - g.rotation.y) * 0.05;
    g.rotation.x += (targetX - g.rotation.x) * 0.05;
  });

  return (
    <group ref={group} scale={0.17}>
      {/* Echo copies behind the main mark give the layered wireframe depth. */}
      {[2.6, 5.2].map((z, i) => (
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
        <pointsMaterial color={ember} size={0.07} sizeAttenuation transparent opacity={0.9} />
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
      <Mark ink={c.ink} ember={c.ember} light={theme === "light"} />
    </Canvas>
  );
}
