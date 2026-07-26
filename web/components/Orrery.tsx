"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, OrbitControls, Preload } from "@react-three/drei";
import * as THREE from "three";
import { useStore } from "@/lib/store";
import { useReducedMotion } from "@/lib/useReducedMotion";
import type { Evidence, Reel } from "@/lib/types";
import { Earth, Jupiter, Mars, Mercury, Moon, OrbitRing, Saturn, Sky, SmallBodies, Sun, Titan, Venus } from "./space/Bodies";
import { CRAFT_LABEL, CRAFT_LIFT, Craft } from "./space/Craft";
import { BodyPickers, FreeRoam } from "./space/Interaction";
import {
  EARTH_CENTER,
  EARTH_RADIUS,
  MARS_CENTER,
  MARS_RADIUS,
  MOON_CENTER,
  SUN_POSITION,
  UNKNOWN_CENTER,
  DEEP_SPACE_CENTER,
  JUPITER_CENTER,
  JUPITER_RADIUS,
  SATURN_CENTER,
  SATURN_RADIUS,
  VENUS_CENTER,
  VENUS_RADIUS,
  MERCURY_CENTER,
  MERCURY_RADIUS,
  TITAN_CENTER,
  TITAN_RADIUS,
  COMET_CENTER,
  ESTABLISHING,
  type Placement,
  bodyCamera,
  focusCamera,
  placeEvidence,
  stageCamera,
} from "./space/stage";

const AXIS_COLOR: Record<string, string> = {
  scene: "#6ddf9c",
  video: "#e8b04b",
  published: "#e2647a",
};

const AXIS_WORD: Record<string, string> = {
  scene: "date stated in this scene",
  video: "date from clip context",
  published: "upload date only",
};

const UP = new THREE.Vector3(0, 1, 0);

/** Only the parts of OrbitControls the rig touches. three's own EventDispatcher types narrow the
 *  event name to never here, so the listener pair is declared by hand. */
interface OrbitControlsLike {
  target: THREE.Vector3;
  update: () => void;
  addEventListener: (type: string, listener: () => void) => void;
  removeEventListener: (type: string, listener: () => void) => void;
}

function easeInOutCubic(x: number): number {
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

/** Beacon plus a selection ring, both billboarded so they stay readable from any angle.
 *  Colour carries `era_axis`, and the hover card repeats it in words: colour is never the
 *  only channel. */
function Beacon({
  color,
  active,
  cited,
  animate,
}: {
  color: string;
  active: boolean;
  cited: boolean;
  animate: boolean;
}) {
  const dot = useRef<THREE.Mesh>(null);
  const ring = useRef<THREE.Mesh>(null);
  const camera = useThree((state) => state.camera);

  useFrame((state) => {
    if (ring.current) ring.current.quaternion.copy(camera.quaternion);
    if (!dot.current) return;
    if (cited && animate) {
      const pulse = 1 + Math.sin(state.clock.elapsedTime * 2.4) * 0.35;
      dot.current.scale.setScalar(pulse);
    } else {
      dot.current.scale.setScalar(1);
    }
  });

  return (
    <group>
      <mesh ref={dot} position={[0, 0.62, 0]}>
        <sphereGeometry args={[0.035, 12, 10]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
      {(active || cited) && (
        <mesh ref={ring} position={[0, 0.2, 0]}>
          <ringGeometry args={[active ? 0.52 : 0.44, active ? 0.56 : 0.465, 48]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={active ? 0.9 : 0.35}
            side={THREE.DoubleSide}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      )}
    </group>
  );
}

function Marker({
  placement,
  active,
  labelled,
  cited,
  animate,
  onSelect,
}: {
  placement: Placement;
  active: boolean;
  /** Show the card without hovering. True for the active shot once the camera is following the
   *  reel; during the establishing shot the active marker is off frame, and its card would sit
   *  in a corner attached to nothing. */
  labelled: boolean;
  cited: boolean;
  animate: boolean;
  onSelect: () => void;
}) {
  const { ev, index, craft, normal, pos } = placement;
  const [hovered, setHovered] = useState(false);
  const color = AXIS_COLOR[ev.era_axis ?? "published"] ?? AXIS_COLOR.published;
  const group = useRef<THREE.Group>(null);
  const camera = useThree((state) => state.camera);

  // Neighbours on the same stage would otherwise loom into the lens when the camera flies in on
  // one of them, filling the frame with an out-of-context solar panel.
  useFrame(() => {
    if (group.current) group.current.visible = active || camera.position.distanceTo(pos) > 1.4;
  });

  // Stand the craft up on the surface normal, so a rover on Mars is not lying on its side.
  const quaternion = useMemo(
    () => new THREE.Quaternion().setFromUnitVectors(UP, normal.clone().normalize()),
    [normal],
  );

  // Small on purpose: a craft a third the width of Mars would read as a toy. The camera
  // closes in on each shot instead, so scale buys realism rather than legibility.
  const scale = 0.45 + Math.min(ev.score, 1) * 0.25;
  const lift = CRAFT_LIFT[craft];

  return (
    <group ref={group} position={pos} quaternion={quaternion}>
      <group scale={scale} position={[0, lift, 0]}>
        <Craft kind={craft} animate={animate} />
        <Beacon color={color} active={active} cited={cited} animate={animate} />

        {/* Generous invisible hit sphere: the craft themselves are small on purpose. */}
        <mesh
          visible={false}
          onClick={(e) => {
            e.stopPropagation();
            onSelect();
          }}
          onPointerOver={(e) => {
            e.stopPropagation();
            setHovered(true);
            document.body.style.cursor = "pointer";
          }}
          onPointerOut={() => {
            setHovered(false);
            document.body.style.cursor = "";
          }}
        >
          <sphereGeometry args={[1.2, 12, 10]} />
        </mesh>
      </group>

      {/* Fixed screen size, not distanceFactor: scaling with distance turns the card into
          wall-sized text once the camera closes to within a couple of units. */}
      {(hovered || labelled) && (
        <Html position={[0, lift + 0.25, 0]} zIndexRange={[40, 0]}>
          <div className="marker-card" data-active={active}>
            <div className="mc-head" style={{ color }}>
              <b>[{index + 1}]</b> {ev.era_start ?? "undated"} · {ev.mission ?? "mission unknown"}
            </div>
            <div className="mc-stage">
              {placement.stageLabel} · {CRAFT_LABEL[craft]}
            </div>
            {ev.text && <div className="mc-text">{ev.text}</div>}
            <div className="mc-meta">
              {ev.title}
              <br />
              {ev.index} {ev.score.toFixed(3)} · {AXIS_WORD[ev.era_axis ?? "published"]}
            </div>
          </div>
        </Html>
      )}
    </group>
  );
}

function BodyLabel({ position, text }: { position: THREE.Vector3; text: string }) {
  return (
    <Html position={position} center zIndexRange={[10, 0]}>
      <div className="body-label">{text}</div>
    </Html>
  );
}

/** Camera follows the reel. Drives both the camera position and the OrbitControls target, then
 *  calls update(): writing camera.lookAt() directly fights the controls and jitters. */
function CameraRig({
  placements,
  activeIndex,
}: {
  placements: Placement[];
  activeIndex: number;
}) {
  const controls = useThree((state) => state.controls) as OrbitControlsLike | null;
  const camera = useThree((state) => state.camera);
  const reduced = useReducedMotion();
  const { cameraMode, autoFollow, setAutoFollow, engaged, focusBody } = useStore();

  const tween = useRef<{
    fromPos: THREE.Vector3;
    fromTarget: THREE.Vector3;
    toPos: THREE.Vector3;
    toTarget: THREE.Vector3;
    start: number;
    duration: number;
  } | null>(null);
  const lastIndex = useRef<number | null>(null);
  const pending = useRef<{ pos: THREE.Vector3; target: THREE.Vector3 } | null>(null);

  // Only a drag or wheel on the canvas suspends the follow. Watching window pointerdown would
  // break follow every time the user clicked a panel button.
  useEffect(() => {
    if (!controls) return;
    const onStart = () => setAutoFollow(false);
    controls.addEventListener("start", onStart);
    return () => controls.removeEventListener("start", onStart);
  }, [controls, setAutoFollow]);

  useEffect(() => {
    if (focusBody) {
      const pose = focusCamera(focusBody);
      lastIndex.current = null;
      pending.current = { pos: pose.camPos, target: pose.lookAt };
      return;
    }

    if (!engaged) {
      lastIndex.current = null;
      pending.current = { pos: ESTABLISHING.camPos.clone(), target: ESTABLISHING.lookAt.clone() };
      return;
    }

    const placement = placements[activeIndex];
    if (!placement) return;

    const pose = cameraMode === "space" ? bodyCamera(placement) : stageCamera(placement);
    const previous = lastIndex.current === null ? null : placements[lastIndex.current];

    // Consecutive shots on one stage get a nudge, not a full re-fly, so a run of Mars surface
    // shots does not swing the camera in a loop. Keyed on the previous shot index rather than a
    // "last stage" string: under StrictMode this effect runs twice per change, and a string ref
    // would make the second run think it was already there and stop a third of the way.
    const sameStage =
      previous !== null &&
      lastIndex.current !== activeIndex &&
      previous.stageKey === placement.stageKey &&
      previous.craft === placement.craft;

    const toPos =
      sameStage && cameraMode !== "space"
        ? camera.position.clone().lerp(pose.camPos, 0.35)
        : pose.camPos;

    lastIndex.current = activeIndex;
    pending.current = { pos: toPos, target: pose.lookAt };
  }, [placements, activeIndex, cameraMode, camera, engaged, focusBody]);

  useFrame((state) => {
    if (!controls) return;

    if (pending.current) {
      if (autoFollow || focusBody) {
        tween.current = {
          fromPos: camera.position.clone(),
          fromTarget: controls.target.clone(),
          toPos: pending.current.pos,
          toTarget: pending.current.target,
          start: state.clock.elapsedTime,
          duration: reduced ? 0 : 1.1,
        };
      }
      pending.current = null;
    }

    if ((!autoFollow && !focusBody) || !tween.current) return;

    const { fromPos, fromTarget, toPos, toTarget, start, duration } = tween.current;
    const elapsed = state.clock.elapsedTime - start;

    if (duration <= 0 || elapsed >= duration) {
      camera.position.copy(toPos);
      controls.target.copy(toTarget);
      tween.current = null;
    } else {
      const t = easeInOutCubic(elapsed / duration);
      camera.position.lerpVectors(fromPos, toPos, t);
      controls.target.lerpVectors(fromTarget, toTarget, t);
    }
    controls.update();
  });

  return null;
}

function CameraFill() {
  const light = useRef<THREE.PointLight>(null);
  const camera = useThree((state) => state.camera);
  useFrame(() => light.current?.position.copy(camera.position));
  return <pointLight ref={light} intensity={2.2} distance={26} decay={1.4} color="#cfe0ff" />;
}

function Scene({
  evidence,
  reel,
  cited,
  animate,
}: {
  evidence: Evidence[];
  reel?: Reel;
  cited: number[];
  animate: boolean;
}) {
  const { activeShotIndex, selectShot, engaged } = useStore();
  const placements = useMemo(() => placeEvidence(evidence), [evidence]);
  const hasUnplaced = placements.some((p) => p.stageKey === "unknown");
  const hasDeepSpace = placements.some((p) => p.stageKey === "deep_space");

  return (
    <>
      {/* Single light source at the Sun, plus a whisper of fill. Space has no fill light, but
          at zero fill the night side of every craft is pure black and unreadable. */}
      <directionalLight position={SUN_POSITION} intensity={2.6} color="#fff4e2" />
      <ambientLight intensity={0.075} color="#93a8c4" />
      <CameraFill />
      <hemisphereLight args={["#2a3d5c", "#0a0d14", 0.12]} />

      <Sky />
      <Sun />
      <Mars />
      <Earth />
      <Moon />
      <Venus />
      <Mercury />
      <Jupiter />
      <Saturn />
      <Titan />
      <SmallBodies />
      <OrbitRing center={EARTH_CENTER} radius={EARTH_RADIUS + 1.8} />
      <OrbitRing center={EARTH_CENTER} radius={MOON_CENTER.distanceTo(EARTH_CENTER)} opacity={0.06} />

      <BodyLabel position={MARS_CENTER.clone().add(new THREE.Vector3(0, MARS_RADIUS + 1.1, 0))} text="Mars" />
      <BodyLabel position={EARTH_CENTER.clone().add(new THREE.Vector3(0, EARTH_RADIUS + 1.4, 0))} text="Earth" />
      <BodyLabel position={MOON_CENTER.clone().add(new THREE.Vector3(0, 2.4, 0))} text="Moon" />
      <BodyLabel position={VENUS_CENTER.clone().add(new THREE.Vector3(0, VENUS_RADIUS + 1.3, 0))} text="Venus" />
      <BodyLabel position={MERCURY_CENTER.clone().add(new THREE.Vector3(0, MERCURY_RADIUS + 1.1, 0))} text="Mercury" />
      <BodyLabel position={JUPITER_CENTER.clone().add(new THREE.Vector3(0, JUPITER_RADIUS + 1.8, 0))} text="Jupiter" />
      <BodyLabel position={SATURN_CENTER.clone().add(new THREE.Vector3(0, SATURN_RADIUS + 1.8, 0))} text="Saturn" />
      <BodyLabel position={TITAN_CENTER.clone().add(new THREE.Vector3(0, TITAN_RADIUS + 1.1, 0))} text="Titan" />
      <BodyLabel position={COMET_CENTER.clone().add(new THREE.Vector3(0, 2.4, 0))} text="small bodies" />
      {hasDeepSpace && (
        <BodyLabel position={DEEP_SPACE_CENTER.clone().add(new THREE.Vector3(0, 3, 0))} text="deep space" />
      )}
      {hasUnplaced && (
        <BodyLabel
          position={UNKNOWN_CENTER.clone().add(new THREE.Vector3(0, 2.6, 0))}
          text="unplaced · body not determined"
        />
      )}

      {placements.map((placement) => (
        <Marker
          key={`${placement.ev.nasa_id}-${placement.ev.start}`}
          placement={placement}
          active={placement.index === activeShotIndex}
          labelled={placement.index === activeShotIndex && engaged}
          cited={cited.includes(placement.index + 1)}
          animate={animate}
          onSelect={() => {
            const shot = reel?.shots?.[placement.index];
            if (shot) selectShot(placement.index, shot.at);
          }}
        />
      ))}

      <BodyPickers />
      <FreeRoam />

      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={0.08}
        minDistance={0.9}
        maxDistance={420}
        zoomSpeed={0.8}
      />
      <CameraRig placements={placements} activeIndex={activeShotIndex} />
      <Preload all />
    </>
  );
}

export default function Orrery({
  evidence,
  reel,
  cited,
}: {
  evidence: Evidence[];
  reel?: Reel;
  cited: number[];
}) {
  const reduced = useReducedMotion();

  return (
    <Canvas
      camera={{ position: [-8, 105, 260], fov: 45, near: 0.05, far: 4000 }}
      dpr={[1, 1.75]}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      onCreated={({ gl }) => {
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 1.05;
      }}
    >
      <Suspense fallback={null}>
        <Scene evidence={evidence} reel={reel} cited={cited} animate={!reduced} />
      </Suspense>
    </Canvas>
  );
}
