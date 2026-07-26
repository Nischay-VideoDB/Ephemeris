"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { useTexture } from "@react-three/drei";
import * as THREE from "three";
import {
  COMET_CENTER,
  JUPITER_CENTER,
  JUPITER_RADIUS,
  MERCURY_CENTER,
  MERCURY_RADIUS,
  SATURN_CENTER,
  SATURN_RADIUS,
  TITAN_CENTER,
  TITAN_RADIUS,
  VENUS_CENTER,
  VENUS_RADIUS,
  EARTH_CENTER,
  EARTH_RADIUS,
  MARS_CENTER,
  MARS_RADIUS,
  MOON_CENTER,
  MOON_RADIUS,
  SUN_POSITION,
  SUN_RADIUS,
} from "./stage";

/* Texture maps are real: Mars is the Viking/MOLA colour and elevation mosaic, Earth is Blue
 * Marble with its normal and specular masks, the Moon is the Clementine mosaic. See
 * public/textures/CREDITS.md. */

const TEX = {
  marsColor: "/textures/mars_color.jpg",
  marsBump: "/textures/mars_bump.jpg",
  earthColor: "/textures/earth_color.jpg",
  earthNormal: "/textures/earth_normal.jpg",
  earthSpecular: "/textures/earth_specular.jpg",
  earthClouds: "/textures/earth_clouds.png",
  moonColor: "/textures/moon_color.jpg",
  moonBump: "/textures/moon_bump.jpg",
  sunColor: "/textures/sun_color.jpg",
  jupiterColor: "/textures/jupiter_color.jpg",
  saturnColor: "/textures/saturn_color.jpg",
  saturnRing: "/textures/saturn_ring.jpg",
  venusColor: "/textures/venus_color.jpg",
  mercuryColor: "/textures/mercury_color.jpg",
};

export const TEXTURE_URLS = Object.values(TEX);

/** Colour maps must be tagged sRGB or every planet comes out washed out. Data maps
 *  (bump, normal, specular) must not be, or the relief reads wrong. */
function useMaps(color: string, extra: string[] = []) {
  const maps = useTexture([color, ...extra]);
  return useMemo(() => {
    maps.forEach((t, i) => {
      t.colorSpace = i === 0 ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      t.anisotropy = 4;
    });
    return maps;
  }, [maps]);
}

/** The Blue Marble specular mask is bright over water, but roughness runs the other way: water is
 *  the smooth surface. Invert it once on a canvas, so the ocean catches a sun glint and the land
 *  stays matte. Feeding the mask in directly gives shiny continents and a chalky sea. */
function invertedTexture(source: THREE.Texture): THREE.Texture {
  const image = source.image as HTMLImageElement | undefined;
  if (!image?.width) return source;

  const canvas = document.createElement("canvas");
  canvas.width = image.width;
  canvas.height = image.height;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(image, 0, 0);
  ctx.globalCompositeOperation = "difference";
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.NoColorSpace;
  return tex;
}

const ATMO_VERT = /* glsl */ `
varying vec3 vNormalW;
varying vec3 vViewDir;
void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vNormalW = normalize(mat3(modelMatrix) * normal);
  vViewDir = normalize(cameraPosition - world.xyz);
  gl_Position = projectionMatrix * viewMatrix * world;
}`;

/** Fresnel rim, dimmed on the night side so the glow does not wrap a planet that is
 *  facing away from the Sun. */
const ATMO_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform vec3 uSun;
uniform float uPower;
uniform float uStrength;
varying vec3 vNormalW;
varying vec3 vViewDir;
void main() {
  float rim = pow(1.0 - max(dot(vNormalW, vViewDir), 0.0), uPower);
  float lit = max(dot(vNormalW, normalize(uSun)), 0.0);
  gl_FragColor = vec4(uColor, rim * uStrength * (0.12 + 0.88 * lit));
}`;

function Atmosphere({
  radius,
  color,
  power = 3.0,
  strength = 1.0,
  scale = 1.035,
}: {
  radius: number;
  color: string;
  power?: number;
  strength?: number;
  scale?: number;
}) {
  const uniforms = useMemo(
    () => ({
      uColor: { value: new THREE.Color(color) },
      uSun: { value: SUN_POSITION.clone().normalize() },
      uPower: { value: power },
      uStrength: { value: strength },
    }),
    [color, power, strength],
  );

  return (
    <mesh scale={scale}>
      <sphereGeometry args={[radius, 48, 32]} />
      <shaderMaterial
        vertexShader={ATMO_VERT}
        fragmentShader={ATMO_FRAG}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </mesh>
  );
}

/** Slow axial spin. Not real rotation periods: at real rates nothing visibly moves, and the
 *  point here is to signal "this is a body, not a decal". */
function useSpin(speed: number) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (ref.current) ref.current.rotation.y += delta * speed;
  });
  return ref;
}

export function Mars() {
  const [color, bump] = useMaps(TEX.marsColor, [TEX.marsBump]);
  const spin = useSpin(0.012);

  return (
    <group position={MARS_CENTER}>
      <group ref={spin} rotation={[0, 0, 0.44]}>
        <mesh>
          <sphereGeometry args={[MARS_RADIUS, 96, 64]} />
          <meshStandardMaterial
            map={color}
            bumpMap={bump}
            bumpScale={0.9}
            roughness={0.92}
            metalness={0}
          />
        </mesh>
      </group>
      {/* Thin, dusty, and pinkish rather than blue. */}
      <Atmosphere radius={MARS_RADIUS} color="#d98a5a" power={3.4} strength={0.55} scale={1.022} />
    </group>
  );
}

export function Earth() {
  const [color, normal, specular, clouds] = useMaps(TEX.earthColor, [
    TEX.earthNormal,
    TEX.earthSpecular,
    TEX.earthClouds,
  ]);
  const spin = useSpin(0.02);
  const cloudSpin = useSpin(0.026);
  const gloss = useMemo(() => invertedTexture(specular), [specular]);
  const normalScale = useMemo(() => new THREE.Vector2(0.7, 0.7), []);

  return (
    <group position={EARTH_CENTER}>
      <group ref={spin} rotation={[0, 0, 0.41]}>
        <mesh>
          <sphereGeometry args={[EARTH_RADIUS, 96, 64]} />
          <meshStandardMaterial
            map={color}
            normalMap={normal}
            normalScale={normalScale}
            roughnessMap={gloss}
            roughness={1}
            metalness={0}
          />
        </mesh>
      </group>
      {/* Clouds ride a hair above the surface on their own slightly faster spin, so the planet
          does not look like a single printed decal. */}
      <group ref={cloudSpin} rotation={[0, 0, 0.41]}>
        <mesh scale={1.008}>
          <sphereGeometry args={[EARTH_RADIUS, 64, 48]} />
          <meshStandardMaterial
            color="#ffffff"
            alphaMap={clouds}
            transparent
            opacity={0.88}
            depthWrite={false}
            roughness={0.95}
          />
        </mesh>
      </group>
      <Atmosphere radius={EARTH_RADIUS} color="#5aa9ff" power={2.6} strength={1.15} scale={1.05} />
    </group>
  );
}

export function Moon() {
  const [color, bump] = useMaps(TEX.moonColor, [TEX.moonBump]);
  const spin = useSpin(0.008);

  return (
    <group position={MOON_CENTER} ref={spin}>
      <mesh>
        <sphereGeometry args={[MOON_RADIUS, 72, 48]} />
        <meshStandardMaterial map={color} bumpMap={bump} bumpScale={0.55} roughness={0.96} metalness={0} />
      </mesh>
    </group>
  );
}

/* The outer solar system, added when the corpus stopped being Mars-only. Same treatment as
 * the inner planets: a real map, one Sun-side light, an atmosphere shell where the body has
 * one. Saturn additionally gets its rings, which are the only reason it reads as Saturn. */

export function Jupiter() {
  const [color] = useMaps(TEX.jupiterColor);
  const spin = useSpin(0.03);
  return (
    <group position={JUPITER_CENTER}>
      <group ref={spin} rotation={[0, 0, 0.05]}>
        <mesh>
          <sphereGeometry args={[JUPITER_RADIUS, 96, 64]} />
          <meshStandardMaterial map={color} roughness={0.95} metalness={0} />
        </mesh>
      </group>
      <Atmosphere radius={JUPITER_RADIUS} color="#e0b98a" power={3.2} strength={0.5} scale={1.02} />
    </group>
  );
}

export function Saturn() {
  const [color, ring] = useMaps(TEX.saturnColor, [TEX.saturnRing]);
  const spin = useSpin(0.028);

  // A ring plane needs its own UVs: the default ring geometry maps u across the segment,
  // not across the radius, so the banding would run the wrong way.
  const ringGeom = useMemo(() => {
    const geometry = new THREE.RingGeometry(SATURN_RADIUS * 1.25, SATURN_RADIUS * 2.25, 128);
    const pos = geometry.attributes.position;
    const uv = geometry.attributes.uv;
    const v3 = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
      v3.fromBufferAttribute(pos, i);
      const t = (v3.length() - SATURN_RADIUS * 1.25) / (SATURN_RADIUS * 1.0);
      uv.setXY(i, t, 0.5);
    }
    return geometry;
  }, []);

  return (
    <group position={SATURN_CENTER} rotation={[0, 0, 0.47]}>
      <group ref={spin}>
        <mesh>
          <sphereGeometry args={[SATURN_RADIUS, 96, 64]} />
          <meshStandardMaterial map={color} roughness={0.95} metalness={0} />
        </mesh>
      </group>
      <mesh geometry={ringGeom} rotation={[Math.PI / 2, 0, 0]}>
        <meshBasicMaterial map={ring} side={THREE.DoubleSide} transparent opacity={0.86} />
      </mesh>
      <Atmosphere radius={SATURN_RADIUS} color="#e8d3a0" power={3.4} strength={0.4} scale={1.02} />
    </group>
  );
}

export function Titan() {
  const spin = useSpin(0.01);
  return (
    <group position={TITAN_CENTER} ref={spin}>
      <mesh>
        <sphereGeometry args={[TITAN_RADIUS, 64, 44]} />
        {/* No public Titan map ships with the texture set, and Titan is a featureless
            orange haze from orbit anyway, so the colour is the honest rendering. */}
        <meshStandardMaterial color="#c98a3c" roughness={1} metalness={0} />
      </mesh>
      <Atmosphere radius={TITAN_RADIUS} color="#e6a94f" power={2.4} strength={1.3} scale={1.09} />
    </group>
  );
}

export function Venus() {
  const [color] = useMaps(TEX.venusColor);
  const spin = useSpin(-0.006);
  return (
    <group position={VENUS_CENTER}>
      <group ref={spin}>
        <mesh>
          <sphereGeometry args={[VENUS_RADIUS, 80, 56]} />
          <meshStandardMaterial map={color} roughness={0.98} metalness={0} />
        </mesh>
      </group>
      <Atmosphere radius={VENUS_RADIUS} color="#f0d9a0" power={2.6} strength={1.1} scale={1.06} />
    </group>
  );
}

export function Mercury() {
  const [color] = useMaps(TEX.mercuryColor);
  const spin = useSpin(0.006);
  return (
    <group position={MERCURY_CENTER} ref={spin}>
      <mesh>
        <sphereGeometry args={[MERCURY_RADIUS, 72, 48]} />
        <meshStandardMaterial map={color} roughness={0.98} metalness={0} />
      </mesh>
    </group>
  );
}

/** Small bodies get a cluster of irregular rocks rather than a sphere: the archive's comet
 *  and asteroid material is about objects that are not round. */
export function SmallBodies() {
  const rocks = useMemo(() => {
    const geometry = new THREE.IcosahedronGeometry(1, 1);
    const pos = geometry.attributes.position;
    const v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      v.multiplyScalar(0.78 + ((i * 37) % 11) / 22);
      pos.setXYZ(i, v.x, v.y, v.z);
    }
    geometry.computeVertexNormals();
    return geometry;
  }, []);

  const layout: [number, number, number, number][] = [
    [0, 0, 0, 1.1],
    [2.4, 0.6, -1.2, 0.55],
    [-2.1, -0.8, 1.4, 0.42],
    [1.2, 1.7, 2.0, 0.3],
  ];

  return (
    <group position={COMET_CENTER}>
      {layout.map(([x, y, z, scale], i) => (
        <mesh key={i} geometry={rocks} position={[x, y, z]} scale={scale} rotation={[i, i * 1.7, 0]}>
          <meshStandardMaterial color="#6b625a" roughness={1} metalness={0.05} />
        </mesh>
      ))}
    </group>
  );
}

/** Radial falloff sprite for the Sun's glow, generated once. Cheaper and safer than a
 *  postprocessing bloom pass on integrated graphics. */
function glowTexture(): THREE.Texture {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad.addColorStop(0.0, "rgba(255,246,214,0.95)");
  grad.addColorStop(0.16, "rgba(255,203,110,0.55)");
  grad.addColorStop(0.42, "rgba(255,140,50,0.16)");
  grad.addColorStop(1.0, "rgba(255,120,40,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function Sun() {
  const [color] = useMaps(TEX.sunColor);
  const glow = useMemo(glowTexture, []);
  const spin = useSpin(0.004);

  return (
    <group position={SUN_POSITION}>
      <group ref={spin}>
        <mesh>
          <sphereGeometry args={[SUN_RADIUS, 64, 48]} />
          <meshBasicMaterial map={color} toneMapped={false} />
        </mesh>
      </group>
      <sprite scale={[SUN_RADIUS * 7, SUN_RADIUS * 7, 1]}>
        <spriteMaterial
          map={glow}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          transparent
          toneMapped={false}
        />
      </sprite>
    </group>
  );
}

/** Faint circle marking the orbital shell that `earth_orbit` moments sit on, so the altitude
 *  reads as deliberate rather than as markers hovering by accident. */
export function OrbitRing({
  center,
  radius,
  tilt = [Math.PI / 2.3, 0, 0.3],
  opacity = 0.12,
}: {
  center: THREE.Vector3;
  radius: number;
  tilt?: [number, number, number];
  opacity?: number;
}) {
  return (
    <mesh position={center} rotation={tilt}>
      <ringGeometry args={[radius - 0.015, radius + 0.015, 160]} />
      <meshBasicMaterial color="#7fb4d8" transparent opacity={opacity} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
  );
}

/** Star background drawn to a canvas once, then mapped to the inside of a large sphere.
 *  A texture beats a particle cloud here: stars stay crisp at every zoom, there is no
 *  popping as the camera flies, and it costs one draw call and zero per-frame work. */
function skyTexture(): THREE.Texture {
  const w = 4096;
  const h = 2048;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#02030a";
  ctx.fillRect(0, 0, w, h);

  // Deterministic PRNG so the sky is identical on every load and across reloads.
  let seed = 20250725;
  const rnd = () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };

  // Milky Way: a broad diagonal band of dust plus a denser star population inside it.
  const bandY = (x: number) => h * 0.52 + Math.sin((x / w) * Math.PI * 2) * h * 0.16;
  for (let i = 0; i < 26000; i++) {
    const x = rnd() * w;
    const spread = (rnd() + rnd() + rnd() - 1.5) * h * 0.075;
    const y = bandY(x) + spread;
    const a = 0.05 + rnd() * 0.1;
    ctx.fillStyle = `rgba(${188 + rnd() * 50},${190 + rnd() * 45},${215 + rnd() * 40},${a})`;
    ctx.fillRect(x, y, 1.4, 1.4);
  }
  for (let i = 0; i < 900; i++) {
    const x = rnd() * w;
    const y = bandY(x) + (rnd() - 0.5) * h * 0.2;
    const r = 12 + rnd() * 60;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    const warm = rnd() > 0.5;
    g.addColorStop(0, warm ? "rgba(120,96,110,0.05)" : "rgba(80,100,140,0.05)");
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  // Field stars, with a colour temperature spread and a few bright ones that get a halo.
  for (let i = 0; i < 9000; i++) {
    const x = rnd() * w;
    const y = rnd() * h;
    const mag = Math.pow(rnd(), 3.2);
    const r = 0.35 + mag * 1.9;
    const temp = rnd();
    const col =
      temp > 0.86
        ? [255, 214, 170]
        : temp > 0.62
          ? [255, 246, 226]
          : temp > 0.2
            ? [232, 240, 255]
            : [196, 214, 255];
    const a = 0.25 + mag * 0.75;
    ctx.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},${a})`;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    if (mag > 0.78) {
      const g = ctx.createRadialGradient(x, y, 0, x, y, r * 6);
      g.addColorStop(0, `rgba(${col[0]},${col[1]},${col[2]},0.28)`);
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, r * 6, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

export function Sky() {
  const tex = useMemo(skyTexture, []);
  return (
    <mesh rotation={[0, 0.6, 0.32]}>
      <sphereGeometry args={[900, 48, 32]} />
      <meshBasicMaterial map={tex} side={THREE.BackSide} toneMapped={false} depthWrite={false} />
    </mesh>
  );
}
