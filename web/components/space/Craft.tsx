"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { CraftKind } from "./stage";

/* Hardware, not primitives. Each craft is assembled from shared geometries and materials at
 * module scope: one allocation per shape for the whole scene, so fourteen craft cost fourteen
 * transforms rather than fourteen sets of buffers. Shapes are family likenesses (a six-wheel
 * rover with a camera mast, a bus with two wings and a high-gain dish), not models of specific
 * spacecraft, because the archive spans dozens of them. */

/** Solar-cell grid, drawn once. A flat dark box at close range reads as a slab; cell lines and a
 *  slight sheen are what make it read as an array. */
function panelTexture(): THREE.Texture {
  const w = 128;
  const h = 64;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#1a2a63";
  ctx.fillRect(0, 0, w, h);

  const sheen = ctx.createLinearGradient(0, 0, w, h);
  sheen.addColorStop(0, "rgba(120,160,255,0.16)");
  sheen.addColorStop(0.5, "rgba(0,0,0,0)");
  sheen.addColorStop(1, "rgba(120,160,255,0.1)");
  ctx.fillStyle = sheen;
  ctx.fillRect(0, 0, w, h);

  ctx.strokeStyle = "rgba(150,185,255,0.45)";
  ctx.lineWidth = 1;
  for (let x = 0; x <= w; x += 16) {
    ctx.beginPath();
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, h);
    ctx.stroke();
  }
  for (let y = 0; y <= h; y += 16) {
    ctx.beginPath();
    ctx.moveTo(0, y + 0.5);
    ctx.lineTo(w, y + 0.5);
    ctx.stroke();
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(3, 2);
  return tex;
}

const M = {
  hull: new THREE.MeshStandardMaterial({ color: "#c9ced8", metalness: 0.82, roughness: 0.34 }),
  foil: new THREE.MeshStandardMaterial({ color: "#c8a44e", metalness: 1.0, roughness: 0.42 }),
  panel: new THREE.MeshStandardMaterial({
    map: panelTexture(),
    color: "#8fa4e8",
    metalness: 0.5,
    roughness: 0.28,
    emissive: new THREE.Color("#0c1642"),
    emissiveIntensity: 0.7,
  }),
  dark: new THREE.MeshStandardMaterial({ color: "#2b3038", metalness: 0.45, roughness: 0.72 }),
  white: new THREE.MeshStandardMaterial({ color: "#e7eaef", metalness: 0.12, roughness: 0.55 }),
  dish: new THREE.MeshStandardMaterial({
    color: "#e9ecf2",
    metalness: 0.35,
    roughness: 0.4,
    side: THREE.DoubleSide,
  }),
  gold: new THREE.MeshStandardMaterial({ color: "#d9a93c", metalness: 1.0, roughness: 0.2 }),
  lit: new THREE.MeshBasicMaterial({ color: "#ffd479", toneMapped: false }),
  concrete: new THREE.MeshStandardMaterial({ color: "#6d7076", metalness: 0.05, roughness: 0.95 }),
  // The Shuttle's underside and the X-15's skin are the two liveries in this archive that a
  // viewer recognises instantly, so they are worth their own materials.
  tile: new THREE.MeshStandardMaterial({ color: "#3a3d44", metalness: 0.1, roughness: 0.9 }),
  inconel: new THREE.MeshStandardMaterial({ color: "#1b1d22", metalness: 0.6, roughness: 0.5 }),
  mirror: new THREE.MeshStandardMaterial({
    color: "#e8c96a",
    metalness: 1.0,
    roughness: 0.12,
    side: THREE.DoubleSide,
  }),
};

const G = {
  wheel: new THREE.CylinderGeometry(0.07, 0.07, 0.055, 18),
  rod: new THREE.CylinderGeometry(0.012, 0.012, 1, 8),
  chassis: new THREE.BoxGeometry(0.5, 0.16, 0.34),
  deckSlat: new THREE.BoxGeometry(0.62, 0.016, 0.15),
  deckFrame: new THREE.BoxGeometry(0.66, 0.012, 0.54),
  head: new THREE.BoxGeometry(0.13, 0.08, 0.08),
  lens: new THREE.CylinderGeometry(0.022, 0.022, 0.03, 12),
  rtg: new THREE.CylinderGeometry(0.055, 0.055, 0.15, 14),
  octDeck: new THREE.CylinderGeometry(0.26, 0.3, 0.09, 8),
  pad: new THREE.CylinderGeometry(0.055, 0.055, 0.02, 12),
  petal: new THREE.CylinderGeometry(0.22, 0.22, 0.014, 20),
  body: new THREE.CylinderGeometry(0.082, 0.082, 0.8, 22),
  nose: new THREE.ConeGeometry(0.082, 0.22, 22),
  fin: new THREE.BoxGeometry(0.016, 0.17, 0.13),
  bell: new THREE.ConeGeometry(0.085, 0.13, 16),
  band: new THREE.CylinderGeometry(0.088, 0.088, 0.04, 22),
  plume: new THREE.ConeGeometry(0.075, 0.5, 16, 1, true),
  bus: new THREE.BoxGeometry(0.24, 0.2, 0.2),
  slat: new THREE.BoxGeometry(0.3, 0.012, 0.15),
  hga: new THREE.SphereGeometry(0.17, 24, 14, 0, Math.PI * 2, 0, Math.PI / 2.7),
  smallDish: new THREE.SphereGeometry(0.22, 24, 14, 0, Math.PI * 2, 0, Math.PI / 2.6),
  nozzle: new THREE.ConeGeometry(0.025, 0.05, 10),
  capsule: new THREE.CapsuleGeometry(0.11, 0.14, 8, 18),
  ring: new THREE.TorusGeometry(0.1, 0.016, 8, 22),
  torso: new THREE.CapsuleGeometry(0.035, 0.06, 6, 12),
  helmet: new THREE.SphereGeometry(0.038, 16, 12),
  limb: new THREE.CapsuleGeometry(0.013, 0.05, 4, 8),
  frameBar: new THREE.BoxGeometry(0.62, 0.014, 0.014),
  frameBarV: new THREE.BoxGeometry(0.014, 0.42, 0.014),
  screen: new THREE.PlaneGeometry(0.6, 0.4),
  pedestal: new THREE.CylinderGeometry(0.05, 0.07, 0.14, 14),
  building: new THREE.BoxGeometry(0.3, 0.13, 0.22),
  windows: new THREE.BoxGeometry(0.302, 0.03, 0.222),
  apron: new THREE.CylinderGeometry(0.42, 0.42, 0.02, 28),
  boom: new THREE.CylinderGeometry(0.008, 0.008, 0.4, 6),

  // Shuttle: a fuselage that tapers to a nose, a delta wing built as a flattened cone so the
  // sweep is real geometry rather than a box, a fin, and the three main engine bells.
  shuttleBody: new THREE.CapsuleGeometry(0.075, 0.34, 8, 20),
  shuttleNose: new THREE.ConeGeometry(0.075, 0.16, 20),
  shuttleWing: new THREE.ConeGeometry(0.30, 0.44, 3),
  shuttleFin: new THREE.ConeGeometry(0.09, 0.2, 3),
  shuttleEngine: new THREE.ConeGeometry(0.035, 0.07, 12),
  shuttleBay: new THREE.BoxGeometry(0.1, 0.02, 0.26),

  // Telescope: an open tube with an aperture ring, two wings, and a secondary on struts.
  scopeTube: new THREE.CylinderGeometry(0.1, 0.11, 0.42, 22, 1, true),
  scopeBack: new THREE.CylinderGeometry(0.11, 0.11, 0.03, 22),
  scopeRing: new THREE.TorusGeometry(0.1, 0.012, 8, 24),
  scopeWing: new THREE.BoxGeometry(0.34, 0.01, 0.17),
  scopeSecondary: new THREE.CylinderGeometry(0.035, 0.035, 0.02, 14),

  // X-15: a black dart. Stubby wings, a wedge tail, a single big chamber.
  daggerBody: new THREE.CapsuleGeometry(0.045, 0.42, 6, 16),
  daggerWing: new THREE.BoxGeometry(0.26, 0.012, 0.09),
  daggerTail: new THREE.BoxGeometry(0.02, 0.11, 0.09),
  daggerChamber: new THREE.ConeGeometry(0.05, 0.09, 14),

  // Deep-space probe: the Voyager/Mariner silhouette is the dish, the bus and the long booms.
  probeDish: new THREE.SphereGeometry(0.26, 26, 16, 0, Math.PI * 2, 0, Math.PI / 2.8),
  probeBus: new THREE.CylinderGeometry(0.09, 0.09, 0.07, 10),
};

/** Uniform grid, no numbers and no plotted values: an invented chart on a screen would read as
 *  data the pipeline never produced. */
function gridTexture(): THREE.Texture {
  const s = 256;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = s;
  const ctx = canvas.getContext("2d")!;
  ctx.clearRect(0, 0, s, s);
  ctx.strokeStyle = "rgba(96,190,240,0.55)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 8; i++) {
    const p = (i / 8) * s;
    ctx.beginPath();
    ctx.moveTo(p, 0);
    ctx.lineTo(p, s);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, p);
    ctx.lineTo(s, p);
    ctx.stroke();
  }
  ctx.strokeStyle = "rgba(120,215,255,0.9)";
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, s - 2, s - 2);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

let gridSingleton: THREE.Texture | null = null;
function useGrid() {
  return useMemo(() => {
    if (!gridSingleton) gridSingleton = gridTexture();
    return gridSingleton;
  }, []);
}

function Rod({
  from,
  to,
  radius = 0.012,
  material = M.dark,
}: {
  from: [number, number, number];
  to: [number, number, number];
  radius?: number;
  material?: THREE.Material;
}) {
  const { position, quaternion, length } = useMemo(() => {
    const a = new THREE.Vector3(...from);
    const b = new THREE.Vector3(...to);
    const dir = b.clone().sub(a);
    const len = dir.length();
    const q = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      dir.clone().normalize(),
    );
    return { position: a.clone().add(b).multiplyScalar(0.5), quaternion: q, length: len };
  }, [from, to]);

  return (
    <mesh
      geometry={G.rod}
      material={material}
      position={position}
      quaternion={quaternion}
      scale={[radius / 0.012, length, radius / 0.012]}
    />
  );
}

function Rover() {
  const wheels: [number, number][] = [
    [-0.2, -0.19],
    [0, -0.19],
    [0.2, -0.19],
    [-0.2, 0.19],
    [0, 0.19],
    [0.2, 0.19],
  ];
  return (
    <group>
      <mesh geometry={G.chassis} material={M.foil} position={[0, 0.17, 0]} />
      {/* Solar deck as three arrays on a frame: gaps and cell lines keep it from reading as a box. */}
      <mesh geometry={G.deckFrame} material={M.dark} position={[0, 0.25, 0]} />
      {[-0.18, 0, 0.18].map((z) => (
        <mesh key={z} geometry={G.deckSlat} material={M.panel} position={[0, 0.263, z]} />
      ))}
      {wheels.map(([x, z], i) => (
        <mesh
          key={i}
          geometry={G.wheel}
          material={M.dark}
          position={[x, 0.07, z]}
          rotation={[0, 0, Math.PI / 2]}
        />
      ))}
      {/* Camera mast, the feature that makes a rover read as a rover at a glance. */}
      <Rod from={[-0.13, 0.26, 0]} to={[-0.13, 0.5, 0]} radius={0.016} material={M.hull} />
      <mesh geometry={G.head} material={M.hull} position={[-0.13, 0.55, 0]} />
      <mesh geometry={G.lens} material={M.dark} position={[-0.07, 0.55, -0.025]} rotation={[0, 0, Math.PI / 2]} />
      <mesh geometry={G.lens} material={M.dark} position={[-0.07, 0.55, 0.025]} rotation={[0, 0, Math.PI / 2]} />
      <mesh geometry={G.rtg} material={M.dark} position={[0.27, 0.26, 0]} rotation={[0, 0, Math.PI / 2]} />
      {/* Instrument arm, stowed forward. */}
      <Rod from={[0.22, 0.15, 0.1]} to={[0.4, 0.06, 0.14]} radius={0.014} material={M.hull} />
      <Rod from={[0.4, 0.06, 0.14]} to={[0.5, 0.03, 0.06]} radius={0.011} material={M.hull} />
    </group>
  );
}

function Lander() {
  const legs = [0, (Math.PI * 2) / 3, (Math.PI * 4) / 3];
  return (
    <group>
      <mesh geometry={G.octDeck} material={M.foil} position={[0, 0.24, 0]} />
      {legs.map((a, i) => {
        const x = Math.cos(a) * 0.3;
        const z = Math.sin(a) * 0.3;
        return (
          <group key={i}>
            <Rod from={[Math.cos(a) * 0.16, 0.22, Math.sin(a) * 0.16]} to={[x, 0.02, z]} radius={0.018} material={M.hull} />
            <mesh geometry={G.pad} material={M.dark} position={[x, 0.02, z]} />
          </group>
        );
      })}
      <mesh geometry={G.petal} material={M.panel} position={[-0.44, 0.27, 0]} />
      <mesh geometry={G.petal} material={M.panel} position={[0.44, 0.27, 0]} />
      <Rod from={[0, 0.28, 0]} to={[0, 0.44, 0]} radius={0.012} material={M.hull} />
      <mesh geometry={G.hga} material={M.dish} position={[0, 0.46, 0]} scale={0.6} />
      {/* Meteorology boom, the thing that always sticks off a lander deck. */}
      <Rod from={[0.1, 0.28, 0.12]} to={[0.34, 0.42, 0.3]} radius={0.008} material={M.hull} />
    </group>
  );
}

function Rocket({ animate }: { animate: boolean }) {
  const plume = useRef<THREE.Mesh>(null);
  useFrame((state) => {
    if (!plume.current || !animate) return;
    const t = state.clock.elapsedTime;
    const flicker = 1 + Math.sin(t * 22) * 0.08 + Math.sin(t * 7.3) * 0.05;
    plume.current.scale.set(flicker, flicker * 1.1, flicker);
    (plume.current.material as THREE.Material).opacity = 0.55 + Math.sin(t * 15) * 0.12;
  });

  const fins = [0, Math.PI / 2, Math.PI, (Math.PI * 3) / 2];

  return (
    <group>
      <mesh geometry={G.body} material={M.white} position={[0, 0.52, 0]} />
      <mesh geometry={G.band} material={M.dark} position={[0, 0.34, 0]} />
      <mesh geometry={G.nose} material={M.white} position={[0, 1.03, 0]} />
      {fins.map((a, i) => (
        <mesh
          key={i}
          geometry={G.fin}
          material={M.dark}
          position={[Math.cos(a) * 0.085, 0.2, Math.sin(a) * 0.085]}
          rotation={[0, -a, 0]}
        />
      ))}
      <mesh geometry={G.bell} material={M.dark} position={[0, 0.06, 0]} rotation={[Math.PI, 0, 0]} />
      <mesh ref={plume} geometry={G.plume} position={[0, -0.28, 0]} rotation={[Math.PI, 0, 0]}>
        <meshBasicMaterial
          color="#ffb057"
          transparent
          opacity={0.6}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          side={THREE.DoubleSide}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}

function Station() {
  return (
    <group>
      <mesh geometry={G.apron} material={M.concrete} position={[0, 0.01, 0]} />
      <mesh geometry={G.building} material={M.hull} position={[0.22, 0.08, 0.16]} />
      {/* Lit windows: the only warm light in the scene that is not the Sun, which reads as
          "people are working here". */}
      <mesh geometry={G.windows} material={M.lit} position={[0.22, 0.09, 0.16]} />
      <mesh geometry={G.pedestal} material={M.hull} position={[-0.08, 0.08, -0.04]} />
      <group position={[-0.08, 0.18, -0.04]} rotation={[-0.7, 0.4, 0]}>
        <mesh geometry={G.smallDish} material={M.dish} />
        <Rod from={[0, 0, 0]} to={[0, 0.2, 0]} radius={0.008} material={M.hull} />
        <mesh geometry={G.pad} material={M.dark} position={[0, 0.2, 0]} scale={[0.5, 1, 0.5]} />
      </group>
    </group>
  );
}

function Orbiter({ animate }: { animate: boolean }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (ref.current && animate) ref.current.rotation.y += delta * 0.12;
  });

  const slats = [-0.16, 0, 0.16];

  return (
    <group ref={ref}>
      <mesh geometry={G.bus} material={M.foil} />
      {[-1, 1].map((side) =>
        slats.map((z, i) => (
          <mesh
            key={`${side}-${i}`}
            geometry={G.slat}
            material={M.panel}
            position={[side * 0.29, 0, z]}
          />
        )),
      )}
      <Rod from={[-0.44, 0, 0]} to={[0.44, 0, 0]} radius={0.009} material={M.hull} />
      <group position={[0, 0.14, 0.14]} rotation={[-0.9, 0, 0]}>
        <mesh geometry={G.hga} material={M.dish} />
        <Rod from={[0, 0, 0]} to={[0, 0.15, 0]} radius={0.006} material={M.hull} />
      </group>
      <mesh geometry={G.nozzle} material={M.dark} position={[0, -0.13, 0]} rotation={[Math.PI, 0, 0]} />
      {/* Radar dipoles. */}
      <Rod from={[0, 0.02, -0.12]} to={[0, 0.02, -0.42]} radius={0.005} material={M.hull} />
    </group>
  );
}

function Capsule({ animate }: { animate: boolean }) {
  const crew = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!crew.current || !animate) return;
    const t = state.clock.elapsedTime;
    crew.current.position.set(0.34 + Math.sin(t * 0.5) * 0.03, 0.16 + Math.sin(t * 0.7) * 0.04, 0.1);
    crew.current.rotation.z = Math.sin(t * 0.4) * 0.2;
  });

  return (
    <group>
      <mesh geometry={G.capsule} material={M.white} rotation={[0, 0, Math.PI / 2]} />
      <mesh geometry={G.ring} material={M.hull} position={[-0.18, 0, 0]} rotation={[0, Math.PI / 2, 0]} />
      <mesh geometry={G.slat} material={M.panel} position={[0, 0, 0.24]} rotation={[0, 0.2, 0]} />
      <mesh geometry={G.slat} material={M.panel} position={[0, 0, -0.24]} rotation={[0, -0.2, 0]} />
      <Rod from={[0.14, 0.04, 0.02]} to={[0.32, 0.15, 0.09]} radius={0.004} material={M.white} />
      <group ref={crew} position={[0.34, 0.16, 0.1]}>
        <mesh geometry={G.torso} material={M.white} />
        <mesh geometry={G.helmet} material={M.white} position={[0, 0.07, 0]} />
        <mesh geometry={G.helmet} material={M.gold} position={[0.016, 0.072, 0.014]} scale={0.86} />
        <mesh geometry={G.limb} material={M.white} position={[0.05, 0.02, 0]} rotation={[0, 0, -0.9]} />
        <mesh geometry={G.limb} material={M.white} position={[-0.05, 0.02, 0]} rotation={[0, 0, 0.9]} />
        <mesh geometry={G.limb} material={M.white} position={[0.02, -0.07, 0]} rotation={[0, 0, -0.25]} />
        <mesh geometry={G.limb} material={M.white} position={[-0.02, -0.07, 0]} rotation={[0, 0, 0.25]} />
      </group>
    </group>
  );
}

function Holo() {
  const grid = useGrid();
  return (
    <group>
      <mesh geometry={G.frameBar} material={M.hull} position={[0, 0.21, 0]} />
      <mesh geometry={G.frameBar} material={M.hull} position={[0, -0.21, 0]} />
      <mesh geometry={G.frameBarV} material={M.hull} position={[-0.31, 0, 0]} />
      <mesh geometry={G.frameBarV} material={M.hull} position={[0.31, 0, 0]} />
      <mesh geometry={G.screen}>
        <meshBasicMaterial
          map={grid}
          transparent
          opacity={0.5}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          side={THREE.DoubleSide}
          toneMapped={false}
        />
      </mesh>
      <Rod from={[0, -0.21, 0]} to={[0, -0.38, 0]} radius={0.008} material={M.hull} />
    </group>
  );
}

function Probe({ animate }: { animate: boolean }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (ref.current && animate) ref.current.rotation.y += delta * 0.2;
  });
  return (
    <group ref={ref}>
      <mesh geometry={G.bus} material={M.foil} scale={[0.7, 0.7, 0.7]} />
      <mesh geometry={G.slat} material={M.panel} position={[0.26, 0, 0]} />
      <mesh geometry={G.hga} material={M.dish} position={[0, 0.1, 0]} scale={0.55} rotation={[-0.3, 0, 0]} />
      <Rod from={[-0.08, 0, 0]} to={[-0.36, 0.06, 0]} radius={0.005} material={M.hull} />
      <mesh geometry={G.nozzle} material={M.dark} position={[0, -0.09, 0]} rotation={[Math.PI, 0, 0]} />
    </group>
  );
}

/** Space Shuttle. Named in 70 of the archive's 87 clips, and until now it flew as a generic
 *  launch vehicle. Delta wing, wedge fin, three main engines, payload bay doors open. */
function Shuttle({ animate }: { animate: boolean }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (ref.current && animate) ref.current.rotation.y += delta * 0.09;
  });

  return (
    <group ref={ref} rotation={[0, 0, 0]}>
      {/* Fuselage lies along Z, nose forward. */}
      <group rotation={[Math.PI / 2, 0, 0]}>
        <mesh geometry={G.shuttleBody} material={M.white} />
        <mesh geometry={G.shuttleNose} material={M.tile} position={[0, 0.32, 0]} />
      </group>

      {/* Delta wing: a three-sided cone flattened into a planform, so the sweep is geometry. */}
      <mesh
        geometry={G.shuttleWing}
        material={M.white}
        position={[0, -0.02, -0.04]}
        rotation={[Math.PI / 2, 0, 0]}
        scale={[1, 1, 0.06]}
      />
      {/* Tiles are the underside, which is what makes it read as the orbiter and not an airliner. */}
      <mesh
        geometry={G.shuttleWing}
        material={M.tile}
        position={[0, -0.035, -0.04]}
        rotation={[Math.PI / 2, 0, 0]}
        scale={[0.98, 0.98, 0.03]}
      />

      <mesh
        geometry={G.shuttleFin}
        material={M.white}
        position={[0, 0.11, -0.2]}
        rotation={[0, 0, 0]}
        scale={[0.12, 1, 1]}
      />

      {/* Payload bay, open: the archive is full of servicing and deploy footage. */}
      {[-0.045, 0.045].map((x) => (
        <mesh
          key={x}
          geometry={G.shuttleBay}
          material={M.white}
          position={[x, 0.075, 0.02]}
          rotation={[0, 0, x < 0 ? 0.9 : -0.9]}
        />
      ))}

      {[[-0.035, -0.02], [0.035, -0.02], [0, 0.03]].map(([x, y], i) => (
        <mesh
          key={i}
          geometry={G.shuttleEngine}
          material={M.dark}
          position={[x, y, -0.28]}
          rotation={[-Math.PI / 2, 0, 0]}
        />
      ))}
    </group>
  );
}

/** Great observatory. Hubble is the single most represented mission in the corpus, 98 scenes,
 *  and Webb appears too. An open tube with an aperture, a secondary on struts, and two wings. */
function Telescope({ animate }: { animate: boolean }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (ref.current && animate) ref.current.rotation.y += delta * 0.1;
  });

  return (
    <group ref={ref}>
      <group rotation={[Math.PI / 2, 0, 0]}>
        <mesh geometry={G.scopeTube} material={M.hull} />
        <mesh geometry={G.scopeBack} material={M.foil} position={[0, -0.22, 0]} />
        <mesh geometry={G.scopeRing} material={M.dark} position={[0, 0.21, 0]} rotation={[Math.PI / 2, 0, 0]} />
        {/* Secondary mirror on struts, the detail that says telescope rather than tank. */}
        <mesh geometry={G.scopeSecondary} material={M.mirror} position={[0, 0.3, 0]} />
        {[0, (Math.PI * 2) / 3, (Math.PI * 4) / 3].map((a, i) => (
          <Rod
            key={i}
            from={[Math.cos(a) * 0.095, 0.2, Math.sin(a) * 0.095]}
            to={[0, 0.3, 0]}
            radius={0.005}
            material={M.hull}
          />
        ))}
      </group>

      {[-1, 1].map((side) => (
        <mesh
          key={side}
          geometry={G.scopeWing}
          material={M.panel}
          position={[side * 0.24, 0, 0]}
        />
      ))}
      <group position={[0, 0.13, -0.1]} rotation={[-1.1, 0, 0]}>
        <mesh geometry={G.hga} material={M.dish} scale={0.7} />
      </group>
    </group>
  );
}

/** X-15 and the rocket planes. 80 scenes, and the aeronautics half of this archive had no
 *  hardware of its own: a research aircraft was flying as a launch vehicle. */
function RocketPlane({ animate }: { animate: boolean }) {
  const plume = useRef<THREE.Mesh>(null);
  useFrame((state) => {
    if (!plume.current || !animate) return;
    const t = state.clock.elapsedTime;
    const flicker = 1 + Math.sin(t * 24) * 0.09;
    plume.current.scale.set(flicker, flicker * 1.2, flicker);
  });

  return (
    <group>
      <group rotation={[Math.PI / 2, 0, 0]}>
        <mesh geometry={G.daggerBody} material={M.inconel} />
      </group>
      {[-1, 1].map((side) => (
        <mesh key={side} geometry={G.daggerWing} material={M.inconel} position={[0, 0, -0.02]} scale={[1, 1, 1]} />
      ))}
      <mesh geometry={G.daggerTail} material={M.inconel} position={[0, 0.055, -0.22]} />
      <mesh geometry={G.daggerTail} material={M.inconel} position={[0, -0.045, -0.22]} scale={[1, 0.7, 1]} />
      <mesh
        geometry={G.daggerChamber}
        material={M.dark}
        position={[0, 0, -0.27]}
        rotation={[-Math.PI / 2, 0, 0]}
      />
      <mesh ref={plume} geometry={G.plume} position={[0, 0, -0.5]} rotation={[-Math.PI / 2, 0, 0]} scale={0.5}>
        <meshBasicMaterial
          color="#cfe6ff"
          transparent
          opacity={0.5}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          side={THREE.DoubleSide}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}

/** Deep-space probe. Mariner and Voyager together account for 118 scenes and both read as one
 *  silhouette: a big high-gain dish over a compact bus, with booms trailing behind it. */
function DeepProbe({ animate }: { animate: boolean }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (ref.current && animate) ref.current.rotation.y += delta * 0.07;
  });

  return (
    <group ref={ref}>
      <mesh geometry={G.probeDish} material={M.dish} position={[0, 0.16, 0]} />
      <mesh geometry={G.probeBus} material={M.foil} position={[0, 0.05, 0]} />
      {/* Magnetometer boom and the RTG arm, the two things that break the symmetry. */}
      <Rod from={[0, 0.05, 0]} to={[0.52, -0.06, 0]} radius={0.005} material={M.hull} />
      <Rod from={[0, 0.05, 0]} to={[-0.3, -0.18, 0.06]} radius={0.007} material={M.hull} />
      <mesh geometry={G.rtg} material={M.dark} position={[-0.3, -0.2, 0.06]} rotation={[0, 0, 0.5]} />
      <Rod from={[0, 0.05, 0]} to={[0, -0.02, -0.34]} radius={0.005} material={M.hull} />
    </group>
  );
}

export function Craft({ kind, animate }: { kind: CraftKind; animate: boolean }) {
  switch (kind) {
    case "rover":
      return <Rover />;
    case "lander":
      return <Lander />;
    case "rocket":
      return <Rocket animate={animate} />;
    case "station":
      return <Station />;
    case "orbiter":
      return <Orbiter animate={animate} />;
    case "capsule":
      return <Capsule animate={animate} />;
    case "holo":
      return <Holo />;
    case "shuttle":
      return <Shuttle animate={animate} />;
    case "telescope":
      return <Telescope animate={animate} />;
    case "rocketplane":
      return <RocketPlane animate={animate} />;
    case "deepprobe":
      return <DeepProbe animate={animate} />;
    default:
      return <Probe animate={animate} />;
  }
}

/** How high off the surface the craft's own origin sits, so grounded craft touch the terrain
 *  instead of hovering or sinking. */
export const CRAFT_LIFT: Record<CraftKind, number> = {
  rover: 0,
  lander: 0,
  rocket: 0,
  station: 0,
  orbiter: 0.24,
  capsule: 0.2,
  holo: 0.42,
  probe: 0.2,
  shuttle: 0.22,
  telescope: 0.26,
  rocketplane: 0.2,
  deepprobe: 0.24,
};

export const CRAFT_LABEL: Record<CraftKind, string> = {
  rover: "surface rover",
  lander: "lander",
  rocket: "launch vehicle",
  station: "ground station",
  orbiter: "orbiter",
  capsule: "crewed spacecraft",
  holo: "visualisation",
  probe: "probe",
  shuttle: "Space Shuttle",
  telescope: "space telescope",
  rocketplane: "research aircraft",
  deepprobe: "deep-space probe",
};
