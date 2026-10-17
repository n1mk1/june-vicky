"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { palette, useTheme } from "@/lib/use-theme";

function fibonacciSphere(n: number, r: number) {
  const pts: number[] = [];
  const phi = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const rad = Math.sqrt(1 - y * y);
    pts.push(Math.cos(phi * i) * rad * r, y * r, Math.sin(phi * i) * rad * r);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  return g;
}

function Orb({ score, ink, ember }: { score: number; ink: string; ember: string }) {
  const shell = useRef<THREE.Group>(null);
  const arc = (score / 100) * Math.PI * 2;
  const { edges, dots } = useMemo(
    () => ({
      edges: new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(1.55, 1)),
      dots: fibonacciSphere(520, 1.25),
    }),
    [],
  );

  useFrame((state, dt) => {
    if (shell.current) {
      shell.current.rotation.y += dt * 0.12;
      shell.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.2) * 0.15 - state.pointer.y * 0.15;
    }
  });

  return (
    <>
      <group ref={shell}>
        <lineSegments geometry={edges}>
          <lineBasicMaterial color={ink} transparent opacity={0.35} />
        </lineSegments>
        <points geometry={dots}>
          <pointsMaterial color={ink} size={0.022} sizeAttenuation transparent opacity={0.55} />
        </points>
      </group>
      {/* Score arc: the share of a full circle the founder has earned. */}
      <mesh rotation={[0, 0, Math.PI / 2]}>
        <torusGeometry args={[2.02, 0.004, 6, 200]} />
        <meshBasicMaterial color={ink} transparent opacity={0.18} />
      </mesh>
      {/* Torus arcs run counter-clockwise from 3 o'clock; rotating by (90° − arc) makes it read clockwise from 12. */}
      <mesh rotation={[0, 0, Math.PI / 2 - arc]}>
        <torusGeometry args={[2.02, 0.012, 8, 200, arc]} />
        <meshBasicMaterial color={ember} />
      </mesh>
    </>
  );
}

export default function ReadinessOrb({ score }: { score: number }) {
  const { theme } = useTheme();
  const c = palette[theme];
  return (
    <Canvas dpr={[1, 1.5]} camera={{ position: [0, 0, 7.6], fov: 38 }} gl={{ antialias: true, alpha: true }} aria-hidden>
      <Orb score={score} ink={c.ink} ember={c.ember} />
    </Canvas>
  );
}
