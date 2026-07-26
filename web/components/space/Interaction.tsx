"use client";

import { useEffect, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import { useStore } from "@/lib/store";
import type { CelestialBody } from "@/lib/types";
import { PICKABLE } from "./stage";

/* Making the scene explorable rather than a diorama: every body is a click target, and the
 * camera can be flown anywhere with the keyboard instead of only orbiting whatever the reel
 * last chose. */

/** One invisible sphere per body, slightly larger than the body itself. Picking against these
 *  rather than the rendered meshes keeps hit testing off the 96-segment spheres, and gives the
 *  small bodies a target big enough to actually hit. */
export function BodyPickers() {
  const { focusBody, setFocusBody } = useStore();
  const [hovered, setHovered] = useState<CelestialBody | null>(null);

  return (
    <>
      {PICKABLE.map((body) => {
        const isHovered = hovered === body.key;
        const isFocused = focusBody === body.key;
        return (
          <group key={body.key} position={body.center}>
            <mesh
              visible={false}
              onPointerOver={(e) => {
                e.stopPropagation();
                setHovered(body.key);
                document.body.style.cursor = "pointer";
              }}
              onPointerOut={() => {
                setHovered((current) => (current === body.key ? null : current));
                document.body.style.cursor = "";
              }}
              onClick={(e) => {
                e.stopPropagation();
                setFocusBody(isFocused ? null : body.key);
              }}
            >
              <sphereGeometry args={[body.radius * 1.25, 16, 12]} />
            </mesh>

            {/* A hairline ring on hover only. Once a body is focused the camera framing and the
                panel already say so, and a ring around a body filling the frame is just a hoop. */}
            {isHovered && !isFocused && <SelectionHalo radius={body.radius} />}

            {isHovered && !isFocused && (
              <Html position={[0, body.radius * 1.5, 0]} center zIndexRange={[30, 0]}>
                <div className="body-hint">{body.label} · click to inspect</div>
              </Html>
            )}
          </group>
        );
      })}
    </>
  );
}

function SelectionHalo({ radius }: { radius: number }) {
  const ring = useRef<THREE.Mesh>(null);
  const camera = useThree((state) => state.camera);
  useFrame(() => {
    if (ring.current) ring.current.quaternion.copy(camera.quaternion);
  });
  return (
    <mesh ref={ring}>
      <ringGeometry args={[radius * 1.22, radius * 1.235, 72]} />
      <meshBasicMaterial
        color="#ece5d8"
        transparent
        opacity={0.55}
        side={THREE.DoubleSide}
        depthWrite={false}
        toneMapped={false}
      />
    </mesh>
  );
}

/** Keyboard flight. WASD moves in the view plane, R/F climb and drop, shift accelerates.
 *  Both the camera and the orbit pivot translate together, so the controls keep working
 *  normally afterwards instead of orbiting a point left behind in space. */
export function FreeRoam() {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as
    | { target: THREE.Vector3; update: () => void }
    | null;
  const setAutoFollow = useStore((state) => state.setAutoFollow);

  const keys = useRef<Record<string, boolean>>({});
  const forward = useRef(new THREE.Vector3());
  const right = useRef(new THREE.Vector3());
  const move = useRef(new THREE.Vector3());

  useFrameKeys(keys);

  useFrame((_, delta) => {
    if (!controls) return;
    const pressed = keys.current;
    const ahead = (pressed.w ? 1 : 0) - (pressed.s ? 1 : 0);
    const strafe = (pressed.d ? 1 : 0) - (pressed.a ? 1 : 0);
    const climb = (pressed.r ? 1 : 0) - (pressed.f ? 1 : 0);
    if (!ahead && !strafe && !climb) return;

    // Speed scales with how far the camera is from what it is looking at, so the same key
    // press crosses open space when zoomed out and creeps when parked next to a rover. Capped:
    // unclamped, one second of W from the establishing shot left the solar system entirely.
    const distance = camera.position.distanceTo(controls.target);
    const speed =
      Math.min(Math.max(distance * 0.35, 0.4), 36) * (pressed.shift ? 3 : 1) * delta;

    camera.getWorldDirection(forward.current);
    right.current.crossVectors(forward.current, camera.up).normalize();

    move.current
      .set(0, 0, 0)
      .addScaledVector(forward.current, ahead * speed)
      .addScaledVector(right.current, strafe * speed)
      .addScaledVector(camera.up, climb * speed);

    camera.position.add(move.current);
    controls.target.add(move.current);
    controls.update();
    // Only on the first frame of a movement. Writing it every frame published a store update
    // sixty times a second and re-rendered everything subscribed to it for as long as a key
    // was held.
    if (useStore.getState().autoFollow) setAutoFollow(false);
  });

  return null;
}

/** Key state as a ref rather than React state: this updates every frame and must not
 *  re-render the scene graph.
 *
 *  Bound in an effect with a teardown, not during render. Registering them during render left
 *  a set of window listeners behind on every remount of the canvas, each one writing into the
 *  ref of a component that no longer exists, and under StrictMode two sets were added the
 *  moment the scene first appeared. */
function useFrameKeys(keys: React.RefObject<Record<string, boolean>>) {
  useEffect(() => {
    const typing = () => {
      const el = document.activeElement;
      return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
    };
    const set = (event: KeyboardEvent, value: boolean) => {
      if (typing()) return;
      const key = event.key.toLowerCase();
      if (["w", "a", "s", "d", "r", "f"].includes(key)) keys.current[key] = value;
      if (key === "shift") keys.current.shift = value;
    };
    const down = (e: KeyboardEvent) => set(e, true);
    const up = (e: KeyboardEvent) => set(e, false);
    // Losing focus mid-press would otherwise leave the camera drifting forever.
    const clear = () => {
      for (const key of Object.keys(keys.current)) keys.current[key] = false;
    };

    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", clear);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", clear);
      clear();
    };
  }, [keys]);
}
