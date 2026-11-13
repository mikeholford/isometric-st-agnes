// Isometric scene of St Agnes, rendered tile by tile by render/run.mjs.
// World units are meters: x east, y up (metres above Ordnance Datum), z south, origin at the center of the area.
import * as THREE from 'three';
import { mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';

THREE.ColorManagement.enabled = false; // colors are painted in sRGB and used as-is, like pixel art

const SUN_AZIMUTH = 250; // keep in sync with scripts/sun.py
const SUN_ELEVATION = 40;
const SLAB = 16; // how far the diorama block reaches below the sea
const CAMERA_ELEVATION = 30; // 2:1 pixel-art isometric
const TOP_MARGIN = 32;
const BACKGROUND = new THREE.Color(0x20242c);
const ROAD_ALPHA = 0.5; // marks road pixels in the color target, see makeGround and the post pass

const DATA = '/data/build';
const TYPES = { house: 0, barn: 1, shed: 2, greenhouse: 3, tank: 4, silo: 5, canopy: 6, church: 7, tower: 8, turret: 9, school: 10, mast: 11, cross: 12, engine: 13, stack: 14, outbuilding: 15 };

const rgb = (r, g, b) => new THREE.Color(r / 255, g / 255, b / 255);
const hash = (x) => {
  const s = Math.sin(x * 12.9898) * 43758.5453;
  return s - Math.floor(s);
};

const WALLS_BARN = [
  [rgb(108, 122, 104), 3], [rgb(78, 96, 80), 2], [rgb(150, 146, 132), 2], [rgb(120, 70, 54), 2], [rgb(96, 102, 108), 2],
];
// Roof colors snap to this palette after a little contrast from the aerial sample.
const ROOFS = [
  rgb(176, 84, 58), rgb(140, 64, 50), rgb(108, 56, 46), rgb(66, 68, 74), rgb(88, 90, 96), rgb(120, 122, 124),
  rgb(150, 150, 146), rgb(184, 182, 176), rgb(120, 92, 70), rgb(98, 114, 98), rgb(214, 214, 206), rgb(44, 48, 56),
];

function pickWeighted(list, r) {
  const total = list.reduce((s, [, w]) => s + w, 0);
  let t = r * total;
  for (const [c, w] of list) if ((t -= w) <= 0) return c;
  return list[0][0];
}

function nearestRoof(c) {
  let best = ROOFS[0], bd = Infinity;
  for (const p of ROOFS) {
    const d = (p.r - c.r) ** 2 * 0.9 + (p.g - c.g) ** 2 * 1.2 + (p.b - c.b) ** 2;
    if (d < bd) { bd = d; best = p; }
  }
  return best;
}

// Facades of a Cornish mining village: killas and granite rubble, lime render in white and cream, a few painted
// fronts. There is no open register of construction years here, so every building draws from one list.
const WALLS_HOUSE = [
  [rgb(236, 232, 220), 6], [rgb(226, 218, 200), 4], [rgb(212, 202, 184), 2], [rgb(170, 158, 142), 3], [rgb(150, 140, 128), 2],
  [rgb(190, 176, 152), 1], [rgb(198, 210, 212), 0.6], [rgb(226, 200, 184), 0.6], [rgb(222, 214, 172), 0.5],
];
const FRAMES = [rgb(240, 238, 230), rgb(240, 238, 230), rgb(60, 78, 92), rgb(84, 108, 96), rgb(70, 64, 60)];

function frameColor(m) {
  if (m.frame_fixed) return rgb(...m.frame_fixed);
  return FRAMES[Math.floor(m.rand * 97) % FRAMES.length];
}

function roofColor(m) {
  if (m.roof_fixed) return rgb(...m.roof_fixed);
  if (!m.roof_rgb) return ROOFS[4];
  if (m.roof_exact) return rgb(...m.roof_rgb);
  const c = rgb(...m.roof_rgb);
  // Push saturation up a bit: the photo is hazy, pixel art is not.
  const hsl = {};
  c.getHSL(hsl);
  c.setHSL(hsl.h, Math.min(1, hsl.s * 1.5), hsl.l);
  return nearestRoof(c);
}

function wallColor(m) {
  if (m.wall_fixed) return rgb(...m.wall_fixed);
  if (m.kind === 'tank') return [rgb(74, 98, 82), rgb(150, 150, 140), rgb(64, 72, 80)][Math.floor(m.rand * 3)];
  if (m.kind === 'silo') return rgb(196, 198, 192);
  if (m.kind === 'barn' || m.kind === 'shed') return pickWeighted(WALLS_BARN, m.rand);
  if (m.kind === 'outbuilding') return pickWeighted(WALLS_HOUSE, m.rand).clone().multiplyScalar(0.9);
  return pickWeighted(WALLS_HOUSE, m.rand);
}

async function fetchF32(url) {
  return new Float32Array(await (await fetch(url)).arrayBuffer());
}

// ---------------------------------------------------------------------------------------------
// Buildings

const buildingVertex = `
attribute vec2 aUv;
attribute float aKind;
attribute float aType;
attribute float aAxis;
attribute vec3 aFrame;
attribute vec2 aAtlas;
varying vec3 vFrame;
varying vec2 vAtlas;
varying vec2 vUv2;
varying float vKind;
varying float vType;
varying float vAxis;
varying vec3 vWorld;
varying vec3 vWorldNormal;
`;

const buildingFragment = `
varying vec2 vUv2;
varying float vKind;
varying float vType;
varying float vAxis;
varying vec3 vWorld;
varying vec3 vWorldNormal;
varying vec3 vFrame;
varying vec2 vAtlas;
uniform sampler2D roofAtlas;

vec3 buildingPattern(vec3 base) {
  vec3 c = base;
  bool wall = vKind > 0.5 && vKind < 1.5;
  bool roof = vKind > 1.5;
  int type = int(vType + 0.5);
  if (wall) {
    if (type == 0) {
      // Houses: a grid of windows per storey, and a darker plinth.
      float fl = mod(vUv2.y, 2.8);
      float col = mod(vUv2.x + 0.4, 3.1);
      // No window above the eaves (vAxis): a gable end stays plain.
      bool win = vUv2.y > 0.5 && vUv2.y - fl + 2.3 < vAxis && fl > 0.85 && fl < 2.15 && col > 0.8 && col < 2.2;
      if (win) {
        c = vec3(0.21, 0.26, 0.33);
        if (fl > 1.95 || col < 0.98) c = vFrame;
      }
      if (vUv2.y < 0.35) c *= 0.72;
    } else if (type == 1 || type == 2) {
      // Barns and sheds: corrugated metal or brick with a concrete plinth.
      if (mod(vUv2.x, 1.2) < 0.3) c *= 0.88;
      if (vUv2.y < 0.9) c = mix(c, vec3(0.6, 0.6, 0.58), 0.6);
      float bay = mod(vUv2.x, 14.0);
      if (type == 1 && bay > 4.0 && bay < 8.0 && vUv2.y < 4.2 && vUv2.y > 0.2) c = vec3(0.36, 0.38, 0.4);
    } else if (type == 15) {
      // Garage, garden shed or lean-to beside a house: a plain wall and a darker plinth.
      if (vUv2.y < 0.3) c *= 0.75;
    } else if (type == 3) {
      // Greenhouse glass: pale with the crop showing through, white mullions.
      c = mix(vec3(0.74, 0.82, 0.84), vec3(0.42, 0.58, 0.42), 0.3);
      if (mod(vUv2.x, 2.0) < 0.28 || mod(vUv2.y, 1.7) < 0.22) c = vec3(0.9, 0.92, 0.92);
    } else if (type == 4) {
      if (mod(vUv2.y, 1.2) < 0.18) c *= 0.85;
    } else if (type == 5) {
      if (mod(vUv2.y, 1.6) < 0.2) c *= 0.82;
    } else if (type == 6) {
      // Canopy: mostly open, just posts.
      if (vUv2.y < 2.6 && mod(vUv2.x, 4.0) > 0.4) c = vec3(0.28, 0.27, 0.25);
    } else if (type == 7) {
      // Church: tall round-arched windows in bays, a darker plinth.
      float cx = mod(vUv2.x + 1.0, 4.2) - 2.1;
      float y = vUv2.y;
      bool arch = y > 6.0 && length(vec2(cx, y - 6.0)) < 0.75;
      if (abs(cx) < 0.75 && y > 2.2 && (y < 6.0 || arch)) {
        c = vec3(0.22, 0.25, 0.32);
        if (mod(y, 1.1) < 0.12 || abs(cx) < 0.06) c = vec3(0.55, 0.56, 0.58);
      }
      if (y < 0.6) c *= 0.78;
    } else if (type == 8) {
      // Church tower: louvred belfry, a clock face below it, a slit window, brick plinth.
      float u = vUv2.x, y = vUv2.y, top = vAxis;
      if (abs(u) < 0.8 && y > top - 3.8 && y < top - 0.9) {
        c = vec3(0.16, 0.16, 0.18);
        if (mod(y, 0.42) < 0.14) c = vec3(0.42, 0.36, 0.3);
      }
      float r = length(vec2(u, y - (top - 5.4)));
      if (r < 0.85) c = r < 0.1 ? vec3(0.15) : (r > 0.72 ? vec3(0.2, 0.2, 0.22) : vec3(0.93, 0.92, 0.86));
      if (abs(u) < 0.28 && y > 4.0 && y < 8.5) c = vec3(0.2, 0.22, 0.28);
      if (y < 0.6) c *= 0.78;
    } else if (type == 9) {
      // Roof turret: white, with arched openings near the top.
      if (abs(vUv2.x) < 0.22 && vUv2.y > vAxis - 1.9 && vUv2.y < vAxis - 0.4) c = vec3(0.18, 0.18, 0.2);
    } else if (type == 10) {
      // 1930s school: tall classroom windows with red frames.
      float col = mod(vUv2.x, 2.0);
      float y = vUv2.y;
      if (col > 0.45 && col < 1.55 && y > 0.9 && y < 3.7) {
        c = vec3(0.22, 0.25, 0.3);
        if (col < 0.58 || col > 1.42 || y < 1.02 || y > 3.58 || abs(y - 2.9) < 0.08) c = vFrame;
      }
      if (y < 0.5) c *= 0.8;
    } else if (type == 13) {
      // Mine engine house: rubble walls of killas in rough courses, tall arched openings with nothing behind them
      // but sky and shadow, a heavier base where the bob wall carried the beam.
      float row = floor(vUv2.y / 0.55);
      float stone = fract(sin(dot(vec2(floor((vUv2.x + mod(row, 2.0) * 0.45) / 0.9), row), vec2(12.9898, 78.233))) * 43758.5453);
      c *= 0.86 + 0.24 * stone;
      float cx = mod(vUv2.x + 1.6, 3.2) - 1.6;
      float y = vUv2.y;
      bool arch = y > 6.4 && length(vec2(cx, y - 6.4)) < 0.62;
      if (abs(cx) < 0.62 && y > 3.6 && (y < 6.4 || arch)) c = vec3(0.13, 0.13, 0.15);
      bool door = y > 1.9 && length(vec2(cx, y - 1.9)) < 0.7;
      if (abs(cx) < 0.7 && (y < 1.9 || door)) c = vec3(0.11, 0.11, 0.12);
      if (y < 0.5) c *= 0.8;
    } else if (type == 14) {
      // Mine stack: stone below, the top third in brick, as the Cornish built them.
      float row = floor(vUv2.y / 0.5);
      float stone = fract(sin(dot(vec2(floor((vUv2.x + mod(row, 2.0) * 0.35) / 0.7), row), vec2(12.9898, 78.233))) * 43758.5453);
      if (vUv2.y > vAxis * 0.66) c = vec3(0.6, 0.34, 0.26) * (0.9 + 0.14 * stone);
      else c *= 0.86 + 0.24 * stone;
      if (vUv2.y > vAxis - 0.5) c *= 0.7;
    } else if (type == 11) {
      // Lattice mast: steel cross-bracing.
      float a = fract((vUv2.x + vUv2.y) / 2.2), b = fract((vUv2.y - vUv2.x) / 2.2);
      c = (a < 0.16 || b < 0.16 || mod(vUv2.y, 2.2) < 0.25) ? vec3(0.78, 0.8, 0.82) : vec3(0.42, 0.44, 0.47);
    }
  } else if (roof) {
    if (type == 13) {
      // A roofless engine house: you look down into the shell.
      c = vec3(0.16, 0.15, 0.15);
    } else if (type >= 8 && type != 10) {
      // Spires and caps: plain slate or metal.
    } else if (type == 3) {
      // Venlo greenhouse roof: rows of glass ridges, lit on one side.
      vec2 dir = vec2(cos(vAxis), sin(vAxis));
      float across = dot(vUv2, vec2(-dir.y, dir.x));
      float t = mod(across, 3.2);
      c = t < 1.6 ? vec3(0.88, 0.92, 0.93) : vec3(0.7, 0.79, 0.82);
      if (t < 0.22) c = vec3(0.56, 0.6, 0.62);
      float along = dot(vUv2, dir);
      if (mod(along, 5.0) < 0.2) c *= 0.93;
    } else {
      // The real roof from the aerial photo, when there is one: solar panels, skylights, chimneys.
      if (vAtlas.x >= 0.0) c = texture2D(roofAtlas, vAtlas).rgb;
      if (vWorldNormal.y < 0.97) {
        // Pitched roof: courses of tiles along the contour.
        if (mod(vWorld.y, 0.55) < 0.16) c *= vAtlas.x >= 0.0 ? 0.93 : 0.86;
      } else if (vAtlas.x < 0.0) {
        // Flat roof without a photo: gravel speckle.
        float n = fract(sin(dot(floor(vUv2 * 2.0), vec2(12.9898, 78.233))) * 43758.5453);
        c *= 0.95 + 0.08 * n;
      }
    }
  }
  return c;
}
`;

async function makeBuildings() {
  const meta = await (await fetch(`${DATA}/buildings.json`)).json();
  const v = await fetchF32(`${DATA}/buildings.bin`);
  const COLS = 12; // x y z, normal, u v, kind, building, atlas u v (see scripts/build_buildings.py)
  const n = v.length / COLS;
  const atlasUv = new Float32Array(n * 2);
  const atlas = await new THREE.TextureLoader().loadAsync(`${DATA}/roof_atlas.png`);
  atlas.generateMipmaps = false;
  atlas.minFilter = THREE.LinearFilter;
  atlas.magFilter = THREE.LinearFilter;
  const pos = new Float32Array(n * 3), nor = new Float32Array(n * 3), uv = new Float32Array(n * 2);
  const kind = new Float32Array(n), type = new Float32Array(n), axis = new Float32Array(n), col = new Float32Array(n * 3);
  const frame = new Float32Array(n * 3);
  const walls = meta.map(wallColor), roofs = meta.map(roofColor), frames = meta.map(frameColor);
  for (let i = 0; i < n; i++) {
    const o = i * COLS;
    atlasUv.set([v[o + 10], v[o + 11]], i * 2);
    pos.set([v[o], v[o + 1], v[o + 2]], i * 3);
    nor.set([v[o + 3], v[o + 4], v[o + 5]], i * 3);
    uv.set([v[o + 6], v[o + 7]], i * 2);
    kind[i] = v[o + 8];
    const b = v[o + 9], m = meta[b];
    type[i] = TYPES[m.kind] ?? 0;
    axis[i] = m.kind === 'greenhouse' ? m.axis : (m.param ?? m.axis);
    frame.set([frames[b].r, frames[b].g, frames[b].b], i * 3);
    const c = kind[i] === 2 ? roofs[b] : walls[b];
    col.set([c.r, c.g, c.b], i * 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.setAttribute('aUv', new THREE.BufferAttribute(uv, 2));
  g.setAttribute('aKind', new THREE.BufferAttribute(kind, 1));
  g.setAttribute('aType', new THREE.BufferAttribute(type, 1));
  g.setAttribute('aAxis', new THREE.BufferAttribute(axis, 1));
  g.setAttribute('aFrame', new THREE.BufferAttribute(frame, 3));
  g.setAttribute('aAtlas', new THREE.BufferAttribute(atlasUv, 2));
  const mat = new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true, side: THREE.DoubleSide });
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.roofAtlas = { value: atlas };
    sh.vertexShader = buildingVertex + sh.vertexShader.replace(
      '#include <begin_vertex>',
      `#include <begin_vertex>
       vUv2 = aUv; vKind = aKind; vType = aType; vAxis = aAxis; vFrame = aFrame; vAtlas = aAtlas;
       vWorld = position; vWorldNormal = normal;`,
    );
    sh.fragmentShader = buildingFragment + sh.fragmentShader.replace(
      '#include <color_fragment>',
      `#include <color_fragment>
       diffuseColor.rgb = buildingPattern(diffuseColor.rgb);`,
    );
  };
  return new THREE.Mesh(g, mat);
}

// ---------------------------------------------------------------------------------------------
// Trees

// Wind-cut sycamore, ash and thorn: deep, dull greens, so a crown reads as a tree and not as a bright ball.
const LEAVES = [rgb(58, 92, 42), rgb(68, 102, 46), rgb(50, 84, 40), rgb(76, 106, 48), rgb(62, 88, 38), rgb(56, 96, 50)];
const SCRUB = [rgb(64, 88, 40), rgb(74, 92, 42), rgb(56, 80, 40), rgb(82, 96, 46)];
const NEEDLES = [rgb(40, 74, 50), rgb(46, 82, 54), rgb(34, 66, 46)];
const BUSH_BELOW = 5.5; // lower than this it is thorn, gorse or a hedge: a bush that sits on the ground, no trunk

function lumpySphere(seed) {
  const g = new THREE.IcosahedronGeometry(1, 2);
  const p = g.attributes.position;
  const seen = new Map();
  for (let i = 0; i < p.count; i++) {
    const key = `${p.getX(i).toFixed(3)},${p.getY(i).toFixed(3)},${p.getZ(i).toFixed(3)}`;
    if (!seen.has(key)) seen.set(key, 0.82 + 0.3 * hash(seen.size * 7.1 + seed * 31.7));
    const k = seen.get(key);
    p.setXYZ(i, p.getX(i) * k, p.getY(i) * k, p.getZ(i) * k);
  }
  // Share vertices so the normals come out smooth: a soft blob instead of a faceted gem.
  const smooth = mergeVertices(g.deleteAttribute('normal').deleteAttribute('uv'));
  smooth.computeVertexNormals();
  return smooth;
}

// Three flat tones per crown: lit, mid and shade, like a cel-shaded illustration.
function toonRamp() {
  const t = new THREE.DataTexture(new Uint8Array([84, 84, 84, 255, 150, 150, 150, 255, 215, 215, 215, 255]), 3, 1);
  t.minFilter = t.magFilter = THREE.NearestFilter;
  t.needsUpdate = true;
  return t;
}

async function makeTrees() {
  const t = await fetchF32(`${DATA}/trees.bin`);
  const N = 11; // x, z, height, crown radius, crown base, kind, r, g, b, seed, ground (scripts/build_trees.py)
  const n = t.length / N;
  const group = new THREE.Group();
  const variants = [0, 1, 2].map(lumpySphere);
  const ramp = toonRamp();
  const leafMat = new THREE.MeshToonMaterial({ gradientMap: ramp });
  const needleMat = new THREE.MeshToonMaterial({ gradientMap: ramp });
  const trunkMat = new THREE.MeshLambertMaterial({ color: rgb(74, 58, 46) });
  // A big tree is a main crown with two smaller boughs beside it; a bush is one low lump.
  const lumps = (h, r, kind) => (kind > 0.5 ? 0 : h >= BUSH_BELOW && r > 2.6 ? 3 : 1);
  const counts = [0, 0, 0];
  let conifers = 0;
  for (let i = 0; i < n; i++) {
    const o = i * N;
    if (t[o + 5] > 0.5) conifers++;
    else for (let j = 0; j < lumps(t[o + 2], t[o + 3], 0); j++) counts[(Math.floor(t[o + 9] * 3) + j) % 3]++;
  }
  const crowns = variants.map((g, k) => new THREE.InstancedMesh(g, leafMat, counts[k]));
  const cones = new THREE.InstancedMesh(new THREE.ConeGeometry(1, 1, 7), needleMat, conifers);
  const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.5, 0.62, 1, 6), trunkMat, n);
  const fill = [0, 0, 0];
  let ci = 0;
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
  const up = new THREE.Vector3(0, 1, 0);
  const put = (k, x, y, z, rx, ry, color) => {
    m.compose(p.set(x, y, z), q, s.set(rx, ry, rx));
    crowns[k].setMatrixAt(fill[k], m);
    crowns[k].setColorAt(fill[k]++, color);
  };
  for (let i = 0; i < n; i++) {
    const [x, z, h, r, , kind, , , , seed, y0] = t.subarray(i * N, i * N + N);
    q.setFromAxisAngle(up, seed * Math.PI * 2);
    const bush = kind < 0.5 && h < BUSH_BELOW;
    // The crown starts a fifth to a third of the way up, so the trunk shows under it and the tree stands on the ground.
    const base = bush ? 0 : Math.min(4.5, h * (0.2 + 0.12 * hash(seed * 53)));
    const trunkW = bush ? 0.001 : Math.min(1.3, 0.45 + h * 0.045);
    const trunkH = bush ? 0.001 : base + (h - base) * 0.45;
    m.compose(p.set(x, y0 + trunkH / 2 - 0.4, z), q, s.set(trunkW, trunkH + 0.8, trunkW));
    trunks.setMatrixAt(i, m);
    if (kind > 0.5) {
      const bottom = Math.min(base, 1.5);
      m.compose(p.set(x, y0 + (bottom + h) / 2, z), q, s.set(r * 0.9, h - bottom, r * 0.9));
      cones.setMatrixAt(ci, m);
      cones.setColorAt(ci++, NEEDLES[Math.floor(seed * 97) % NEEDLES.length]);
      continue;
    }
    const k = Math.floor(seed * 3) % 3;
    const palette = bush ? SCRUB : LEAVES;
    const c = palette[Math.floor(seed * 1013) % palette.length].clone().multiplyScalar(0.9 + 0.2 * hash(seed * 77));
    if (bush) {
      // Wider than it is high, and a little into the ground so no gap shows on a slope.
      put(k, x, y0 + h * 0.42, z, Math.max(r, h * 0.55), h * 0.6, c);
      continue;
    }
    const half = Math.max(1.2, (h - base) / 2);
    const wide = Math.min(r, half * 1.5); // never a disc on a stick
    put(k, x, y0 + h - half, z, wide, half, c);
    for (let j = 1; j < lumps(h, r, 0); j++) {
      const a = (seed * 9 + j * 0.47) * Math.PI * 2, d = wide * 0.55, f = 0.62 + 0.14 * hash(seed * 31 + j);
      put((k + j) % 3, x + Math.cos(a) * d, y0 + base + half * f * 0.95, z + Math.sin(a) * d, wide * f, half * f, c.clone().multiplyScalar(0.94 + 0.1 * hash(seed * 13 + j)));
    }
  }
  for (const mesh of [...crowns, cones, trunks]) {
    mesh.frustumCulled = false;
    group.add(mesh);
  }
  return group;
}

// ---------------------------------------------------------------------------------------------
// Ground, sea and diorama block

// The terrain: a grid of heights (scripts/build_terrain.py), row 0 at the north edge.
async function loadTerrain(area) {
  const t = area.terrain;
  const h = await fetchF32(`${DATA}/terrain.bin`);
  const at = (c, r) => h[Math.min(t.ny, Math.max(0, r)) * (t.nx + 1) + Math.min(t.nx, Math.max(0, c))];
  return { ...t, h, at };
}

// One mesh per 500 m chunk, draped over the terrain. Each samples two textures (scripts/build_ground.py): the soft
// ground, and the roads' own colours with the road surface in the alpha channel. Cutting that alpha at one half
// gives roads an edge as sharp as a building's; alpha ROAD_ALPHA in the colour target marks road pixels for the
// post pass, which keeps the painterly filter off them so it can't round those edges.
async function makeGround(renderer, area, terrain) {
  const group = new THREE.Group();
  const loader = new THREE.TextureLoader();
  const size = area.chunk, n = Math.round(size / terrain.res);
  const load = async (url) => {
    const tex = await loader.loadAsync(url);
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    tex.generateMipmaps = true;
    tex.minFilter = THREE.LinearMipmapLinearFilter;
    tex.magFilter = THREE.LinearFilter;
    tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
    tex.premultiplyAlpha = false;
    return tex;
  };
  const index = [];
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      const a = r * (n + 1) + c, b = a + 1, d = a + n + 1, e = d + 1;
      index.push(a, d, b, b, d, e);
    }
  }
  const jobs = [];
  for (let ix = 0; ix < area.nx; ix++) {
    for (let iy = 0; iy < area.ny; iy++) {
      jobs.push(Promise.all([load(`${DATA}/ground/${ix}_${iy}.png`), load(`${DATA}/roads/${ix}_${iy}.png`)]).then(([tex, road]) => {
        const pos = new Float32Array((n + 1) * (n + 1) * 3), uv = new Float32Array((n + 1) * (n + 1) * 2);
        const c0 = ix * n, r0 = (area.ny - 1 - iy) * n; // iy counts from the south edge, terrain rows from the north
        for (let r = 0; r <= n; r++) {
          for (let c = 0; c <= n; c++) {
            const i = r * (n + 1) + c;
            pos.set([-area.hx + (c0 + c) * terrain.res, terrain.at(c0 + c, r0 + r), -area.hz + (r0 + r) * terrain.res], i * 3);
            uv.set([c / n, 1 - r / n], i * 2);
          }
        }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
        geo.setIndex(index);
        const mat = new THREE.ShaderMaterial({
          uniforms: { ground: { value: tex }, road: { value: road }, roadAlpha: { value: ROAD_ALPHA } },
          vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
          fragmentShader: `uniform sampler2D ground; uniform sampler2D road; uniform float roadAlpha; varying vec2 vUv;
            void main() {
              vec4 r = texture2D(road, vUv);
              gl_FragColor = r.a > 0.5 ? vec4(r.rgb, roadAlpha) : vec4(texture2D(ground, vUv).rgb, 1.0);
            }`,
          blending: THREE.NoBlending,
          side: THREE.DoubleSide,
        });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.userData.ground = true;
        mesh.frustumCulled = false;
        group.add(mesh);
      }));
    }
  }
  await Promise.all(jobs);
  return group;
}

// The sides of the diorama block: the rock St Agnes stands on, cut along the edge of the map. Killas (slate) in
// bands, a few ochre and red-brown lodes for the tin and copper, soil on top, and the sea where the edge is water.
function makeSlab(area, terrain) {
  const base = terrain.sea - SLAB;
  const pos = [], top = [], sea = [], shade = [], along = [];
  const strip = (cells, light) => {
    // cells: [x, z, column, row] along one edge, in the order that makes the quads face outward.
    for (let i = 1; i < cells.length; i++) {
      const [ax, az, ac, ar] = cells[i - 1], [bx, bz, bc, br] = cells[i];
      const ha = terrain.at(ac, ar), hb = terrain.at(bc, br);
      const wet = ha <= terrain.sea + 0.01 && hb <= terrain.sea + 0.01 ? 1 : 0;
      pos.push(ax, ha, az, ax, base, az, bx, hb, bz, bx, hb, bz, ax, base, az, bx, base, bz);
      top.push(ha, ha, hb, hb, ha, hb);
      const s0 = (i - 1) * terrain.res, s1 = i * terrain.res;
      along.push(s0, s0, s1, s1, s0, s1);
      for (let k = 0; k < 6; k++) sea.push(wet), shade.push(light);
    }
  };
  const xs = [...Array(terrain.nx + 1).keys()], zs = [...Array(terrain.ny + 1).keys()];
  const X = (c) => -area.hx + c * terrain.res, Z = (r) => -area.hz + r * terrain.res;
  // The sun stands in the west-south-west: the west and south faces are lit, the other two in shade.
  strip(xs.map((c) => [X(c), Z(terrain.ny), c, terrain.ny]), 0.92); // south
  strip(zs.map((r) => [X(0), Z(r), 0, r]), 1.0); // west
  strip(xs.map((c) => [X(c), Z(0), c, 0]), 0.62); // north
  strip(zs.map((r) => [X(terrain.nx), Z(r), terrain.nx, r]), 0.7); // east
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('aTop', new THREE.Float32BufferAttribute(top, 1));
  geo.setAttribute('aSea', new THREE.Float32BufferAttribute(sea, 1));
  geo.setAttribute('aShade', new THREE.Float32BufferAttribute(shade, 1));
  geo.setAttribute('aAlong', new THREE.Float32BufferAttribute(along, 1));
  const mat = new THREE.ShaderMaterial({
    side: THREE.DoubleSide,
    blending: THREE.NoBlending,
    vertexShader: `attribute float aTop; attribute float aSea; attribute float aShade; attribute float aAlong;
      varying float vTop; varying float vSea; varying float vShade; varying float vAlong; varying float vY;
      void main() { vTop = aTop; vSea = aSea; vShade = aShade; vAlong = aAlong; vY = position.y;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `varying float vTop; varying float vSea; varying float vShade; varying float vAlong; varying float vY;
      float hash(float n) { return fract(sin(n * 12.9898) * 43758.5453); }
      void main() {
        float depth = vTop - vY;
        // Beds of slate, tilted a little and of uneven thickness.
        float bed = vY + 0.06 * vAlong + 1.6 * sin(vAlong * 0.011) + 0.8 * sin(vAlong * 0.037);
        float k = floor(bed / 2.6);
        float r = hash(k);
        vec3 c = mix(vec3(0.36, 0.33, 0.31), vec3(0.52, 0.47, 0.42), r);
        if (r > 0.86) c = vec3(0.62, 0.42, 0.26);        // ochre: an iron-stained lode
        else if (r < 0.07) c = vec3(0.45, 0.25, 0.2);    // red-brown: tin ground
        else if (r > 0.78) c = vec3(0.66, 0.63, 0.58);   // pale: a granite or elvan sheet
        if (fract(bed / 2.6) < 0.1) c *= 0.74;           // the joint between two beds
        if (vSea > 0.5) {
          if (depth < 7.0) c = mix(vec3(0.24, 0.6, 0.68), vec3(0.07, 0.27, 0.42), depth / 7.0);
          else if (depth < 7.6) c = vec3(0.78, 0.7, 0.52); // sand on the sea bed
        } else if (depth < 0.9) {
          c = vec3(0.3, 0.23, 0.16); // soil
        }
        gl_FragColor = vec4(c * vShade, 1.0);
      }`,
  });
  const walls = new THREE.Mesh(geo, mat);
  walls.frustumCulled = false;
  walls.userData.ground = true;
  return walls;
}

// ---------------------------------------------------------------------------------------------
// Camera, lights and the outline pass

const deg = Math.PI / 180;

// look: the compass direction the camera looks in, in degrees; 45 is north-east, and every quarter turn works.
function makeCamera(scale, area, look, terrain) {
  const el = CAMERA_ELEVATION * deg, az = look * deg;
  // Screen x of a ground point is x cos(az) + z sin(az), its depth x sin(az) - z cos(az): at the corners of the area
  // that reaches hx |cos| + hz |sin| and hx |sin| + hz |cos|. Looking north-east, both are (hx + hz) / sqrt(2).
  const u = area.hx * Math.abs(Math.cos(az)) + area.hz * Math.abs(Math.sin(az));
  const vGround = (area.hx * Math.abs(Math.sin(az)) + area.hz * Math.abs(Math.cos(az))) * Math.sin(el);
  const width = Math.round(2 * u * scale);
  // Screen height of a point is its ground position plus its height times cos(el).
  const top = vGround + terrain.max * Math.cos(el) + TOP_MARGIN;
  const bottom = -vGround + (terrain.sea - SLAB) * Math.cos(el) - 6;
  const height = Math.round((top - bottom) * scale);
  const cam = new THREE.OrthographicCamera(-width / scale / 2, width / scale / 2, top, top - height / scale, 10, 9000);
  const fwd = new THREE.Vector3(Math.cos(el) * Math.sin(az), -Math.sin(el), -Math.cos(el) * Math.cos(az));
  cam.position.copy(fwd.multiplyScalar(-4000));
  cam.up.set(0, 1, 0);
  cam.lookAt(0, 0, 0);
  return { cam, width, height };
}

function makeLights(scene) {
  const az = SUN_AZIMUTH * deg, el = SUN_ELEVATION * deg;
  // Toward the sun, in world axes: east = +x, north = -z.
  const dir = new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el));
  const sun = new THREE.DirectionalLight(0xfff4e0, 0.95 * Math.PI);
  sun.position.copy(dir.multiplyScalar(1000));
  scene.add(sun);
  scene.add(new THREE.HemisphereLight(0xc8d8f0, 0x6a6450, 0.62 * Math.PI));
}

const outlineShader = {
  uniforms: { tColor: { value: null }, tDepth: { value: null }, texel: { value: new THREE.Vector2() }, range: { value: 1 }, bg: { value: BACKGROUND }, radius: { value: 0 },
    stride: { value: 1 }, ink: { value: 1 }, objectsPass: { value: false }, invViewProj: { value: new THREE.Matrix4() } },
  vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
  fragmentShader: `
    uniform sampler2D tColor; uniform sampler2D tDepth; uniform vec2 texel; uniform float range; uniform vec3 bg; uniform int radius;
    uniform float stride; uniform float ink;
    uniform bool objectsPass; uniform mat4 invViewProj;
    varying vec2 vUv;
    float depthAt(vec2 uv) { return texture2D(tDepth, uv).x * range; }

    // Kuwahara filter: each pixel takes the mean of whichever neighbouring quadrant is the most uniform.
    // It flattens grain into painted areas but keeps edges, the look of a hand-coloured illustration.
    // Road pixels (alpha below 0.75, see makeGround) are skipped: a flat road would otherwise win every quadrant
    // next to it and spread over the verge.
    // The taps lie a quarter of a metre apart (stride pixels), the grain of the ground textures, whatever the
    // resolution of the render: a sharper render gets the same painted areas with finer edges, at the same cost.
    vec3 kuwahara(vec2 uv) {
      vec3 bestMean = texture2D(tColor, uv).rgb;
      float bestVar = 1e9;
      for (int q = 0; q < 4; q++) {
        vec2 dir = vec2(q == 1 || q == 3 ? 1.0 : -1.0, q >= 2 ? 1.0 : -1.0);
        vec3 m = vec3(0.0), s = vec3(0.0);
        float n = 0.0;
        for (int j = 0; j <= 4; j++) {
          for (int i = 0; i <= 4; i++) {
            if (i > radius || j > radius) continue;
            vec4 c = texture2D(tColor, uv + dir * vec2(float(i), float(j)) * stride * texel);
            if (c.a < 0.75) continue;
            m += c.rgb; s += c.rgb * c.rgb; n += 1.0;
          }
        }
        if (n < 1.0) continue;
        m /= n;
        vec3 v = s / n - m * m;
        float var = v.r + v.g + v.b;
        if (var < bestVar) { bestVar = var; bestMean = m; }
      }
      return bestMean;
    }

    void main() {
      if (objectsPass) {
        // A mask of what stands up from the ground: the scene is drawn with buildings, trees and masts in white and
        // the ground in black (see main). The viewer draws this part of the map again over the cars and walkers that
        // are behind it.
        gl_FragColor = vec4(vec3(texture2D(tColor, vUv).r > 0.5 ? 1.0 : 0.0), 1.0);
        return;
      }
      vec4 c = texture2D(tColor, vUv);
      if (radius > 0 && c.a >= 0.75) c.rgb = kuwahara(vUv);
      float d = depthAt(vUv);
      float gap = 0.0;
      // The neighbours are a fifth of a metre away (ink pixels), so the line keeps its weight in a sharper render.
      gap = max(gap, depthAt(vUv + vec2(texel.x * ink, 0.0)) - d);
      gap = max(gap, depthAt(vUv - vec2(texel.x * ink, 0.0)) - d);
      gap = max(gap, depthAt(vUv + vec2(0.0, texel.y * ink)) - d);
      gap = max(gap, depthAt(vUv - vec2(0.0, texel.y * ink)) - d);
      // A big step in depth means this pixel is the near side of a silhouette: ink it.
      if (gap > 2.2) c.rgb *= 0.58;
      gl_FragColor = vec4(c.rgb, 1.0);
    }`,
};

// ---------------------------------------------------------------------------------------------

async function main() {
  const params = new URLSearchParams(location.search);
  const scale = parseFloat(params.get('scale') || '3');
  const radius = parseInt(params.get('kuwahara') || '0');
  const objectsPass = params.get('pass') === 'objects';
  const look = parseFloat(params.get('look') || '45');
  // Supersampling: every tile is rendered ss times as large each way and then averaged down, which smooths the
  // edges of roofs, walls and crowns that a single sample per pixel leaves jagged.
  const ss = Math.max(1, parseInt(params.get('ss') || '1'));
  const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  renderer.setPixelRatio(1);
  document.body.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = BACKGROUND;
  makeLights(scene);
  const area = await (await fetch(`${DATA}/area.json`)).json();
  area.hx = (area.xmax - area.xmin) / 2;
  area.hz = (area.ymax - area.ymin) / 2;
  const terrain = await loadTerrain(area);
  const [ground, buildings, trees] = await Promise.all([makeGround(renderer, area, terrain), makeBuildings(), makeTrees()]);
  scene.add(ground, buildings, trees, makeSlab(area, terrain));
  if (objectsPass) {
    scene.background = new THREE.Color(0x000000);
    const white = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide });
    const black = new THREE.MeshBasicMaterial({ color: 0x000000, side: THREE.DoubleSide });
    scene.traverse((o) => { if (o.isMesh) o.material = o.userData.ground ? black : white; });
  }

  const { cam, width, height } = makeCamera(scale, area, look, terrain);
  let target = null;
  const post = new THREE.ShaderMaterial(outlineShader);
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), post);
  const postScene = new THREE.Scene();
  postScene.add(quad);
  const postCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  function ensureTarget(w, h) {
    if (target && target.width === w && target.height === h) return;
    target?.dispose();
    target = new THREE.WebGLRenderTarget(w, h, { depthBuffer: true });
    target.depthTexture = new THREE.DepthTexture(w, h, THREE.FloatType);
    target.texture.minFilter = target.texture.magFilter = THREE.NearestFilter;
  }

  const crop = document.createElement('canvas');
  window.renderTile = (tx, ty, tw, th) => {
    const m = 8; // margin in pixels, cropped off again below
    const x = (tx - m) * ss, y = (ty - m) * ss, w = (tw + 2 * m) * ss, h = (th + 2 * m) * ss;
    renderer.setSize(w, h, false);
    ensureTarget(w, h);
    cam.setViewOffset(width * ss, height * ss, x, y, w, h);
    cam.updateProjectionMatrix();
    renderer.setRenderTarget(target);
    renderer.render(scene, cam);
    post.uniforms.tColor.value = target.texture;
    post.uniforms.tDepth.value = target.depthTexture;
    post.uniforms.texel.value.set(1 / w, 1 / h);
    post.uniforms.range.value = cam.far - cam.near;
    post.uniforms.radius.value = radius;
    post.uniforms.stride.value = Math.max(1, (scale * ss) / 4);
    post.uniforms.ink.value = Math.max(1, Math.round(scale * ss * 0.2));
    post.uniforms.objectsPass.value = objectsPass;
    post.uniforms.invViewProj.value.multiplyMatrices(cam.projectionMatrix, cam.matrixWorldInverse).invert();
    renderer.setRenderTarget(null);
    renderer.render(postScene, postCam);
    crop.width = tw;
    crop.height = th;
    const ctx = crop.getContext('2d');
    ctx.imageSmoothingQuality = 'high'; // each pixel the mean of the ss by ss it was rendered as
    ctx.drawImage(renderer.domElement, m * ss, m * ss, tw * ss, th * ss, 0, 0, tw, th);
    return crop.toDataURL('image/png');
  };
  window.sceneInfo = { width, height, scale, top: cam.top, look, area };
  window.ready = true;
}

main().catch((e) => {
  window.loadError = String(e.stack || e);
  console.error(e);
});
