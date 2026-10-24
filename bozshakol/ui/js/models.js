// 3D models of the Bozshakol equipment and plant, built from primitives.
// Proportions follow the real machines (CAT 785C / 777D, Hitachi EX3600-6,
// CAT 993K, Sandvik D55SP); the scene scales the mobile fleet up ×1.6 so it
// stays readable from the overview camera.
import * as THREE from '../vendor/three/three.module.min.js';
import { claddingTexture, windowsTexture, softSprite } from './textures.js';

// ------------------------------------------------------------------ materials
const cache = {};
export const nightMats = [];   // {mat, base}: emissive that lights up at night
export const glowMats = [];    // additive beams/pools, opacity follows the night

// Visual style: 'diorama' (default — a miniature on a soil block, rounded
// toy-like machines, painted materials) or 'real' (steppe to the horizon).
export const STYLE = { diorama: true };
export function setStyle(name) { STYLE.diorama = name !== 'real'; }

export function std(color, o = {}) {
  const { unique, ...rest } = o;
  const key = color + JSON.stringify(rest, (k, val) => (val && val.isTexture ? val.uuid : val));
  if (!unique && cache[key]) return cache[key];
  const opts = { roughness: 0.75, metalness: 0.1, ...rest };
  if (STYLE.diorama && !opts.map) {
    // painted, slightly satin surfaces: fewer metallic reflections
    opts.metalness = Math.min(opts.metalness, 0.08 + opts.metalness * 0.25);
    opts.roughness = Math.max(0.42, Math.min(0.85, opts.roughness));
  }
  const m = new THREE.MeshStandardMaterial({ color, ...opts });
  if (!unique) cache[key] = m;
  return m;
}
export const M = {
  catYellow: () => std('#f0b21a', { roughness: 0.45, metalness: 0.25 }),
  hitachi: () => std('#ee7a1c', { roughness: 0.45, metalness: 0.25 }),
  steel: () => std('#8b949c', { roughness: 0.45, metalness: 0.75 }),
  darkSteel: () => std('#3a3f45', { roughness: 0.6, metalness: 0.6 }),
  rubber: () => std('#1d1e20', { roughness: 0.92, metalness: 0 }),
  glass: () => std('#1c2833', { roughness: 0.08, metalness: 0.6 }),
  concrete: () => std('#b9b5ab', { roughness: 0.9, metalness: 0 }),
  white: () => std('#e9e7e2', { roughness: 0.55, metalness: 0.1 }),
  red: () => std('#c63a2c', { roughness: 0.5, metalness: 0.2 }),
};
function emissive(color, base = 2.2) {
  const m = new THREE.MeshStandardMaterial({ color: '#222', emissive: color, emissiveIntensity: 0, roughness: 0.4 });
  nightMats.push({ mat: m, base });
  return m;
}
let spriteTex = null;
function glow(color, opacity = 0.5) {
  spriteTex = spriteTex || softSprite();
  const m = new THREE.MeshBasicMaterial({ color, map: spriteTex, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending });
  glowMats.push({ mat: m, base: opacity });
  return m;
}
export function setNight(night, time = 0) {
  // In the diorama the lamps and windows glow softly by day too.
  const lit = STYLE.diorama ? 0.22 + 0.78 * night : night;
  for (const n of nightMats) n.mat.emissiveIntensity = n.base * lit * (n.blink ? 0.5 + 0.5 * Math.sin(time * 6 + n.blink) : 1);
  for (const g of glowMats) g.mat.opacity = g.base * night;
}

// ------------------------------------------------------------------ helpers
// Box with rounded edges and corners (soft highlights on every edge, as in a
// scale model). Grid vertices are packed near the edges, then pushed onto a
// sphere of radius r around the inner box; normals point away from it.
const rbCache = new Map();
export function roundedBoxGeometry(w, h, d, r, seg = 2) {
  r = Math.max(0, Math.min(r, w / 2 - 1e-3, h / 2 - 1e-3, d / 2 - 1e-3));
  const key = [w, h, d, r, seg].map((x) => x.toFixed(3)).join('|');
  if (rbCache.has(key)) return rbCache.get(key);
  const n = seg * 2 + 1;
  const g = new THREE.BoxGeometry(1, 1, 1, n, n, n);
  const pos = g.attributes.position, nor = g.attributes.normal;
  const half = [w / 2, h / 2, d / 2];
  const map = (u, hf) => {        // u in [-0.5, 0.5] on an even grid -> packed coordinate
    const i = Math.round((u + 0.5) * n);
    if (i <= seg) return -hf + r * (i / seg);
    return hf - r * ((n - i) / seg);
  };
  const p = new THREE.Vector3(), inner = new THREE.Vector3(), dd = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    p.set(map(pos.getX(i), half[0]), map(pos.getY(i), half[1]), map(pos.getZ(i), half[2]));
    inner.set(THREE.MathUtils.clamp(p.x, -half[0] + r, half[0] - r), THREE.MathUtils.clamp(p.y, -half[1] + r, half[1] - r),
      THREE.MathUtils.clamp(p.z, -half[2] + r, half[2] - r));
    dd.subVectors(p, inner);
    const L = dd.length();
    if (L > 1e-6 && r > 0) {
      dd.multiplyScalar(1 / L);
      p.copy(inner).addScaledVector(dd, r);
      nor.setXYZ(i, dd.x, dd.y, dd.z);
    }
    pos.setXYZ(i, p.x, p.y, p.z);
  }
  pos.needsUpdate = true; nor.needsUpdate = true;
  g.computeBoundingSphere();
  rbCache.set(key, g);
  return g;
}
export function box(w, h, d, m) {
  const minD = Math.min(w, h, d);
  const geo = STYLE.diorama && minD > 0.35 ? roundedBoxGeometry(w, h, d, Math.min(minD * 0.18, 2.4), minD > 4 ? 3 : 2) : new THREE.BoxGeometry(w, h, d);
  const mesh = new THREE.Mesh(geo, typeof m === 'string' ? std(m) : m);
  mesh.castShadow = true; mesh.receiveShadow = true;
  return mesh;
}
export function cyl(rt, rb, h, m, seg = 24) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), typeof m === 'string' ? std(m) : m);
  mesh.castShadow = true; mesh.receiveShadow = true;
  return mesh;
}
function at(o, x, y, z, ry = 0) { o.position.set(x, y, z); if (ry) o.rotation.y = ry; return o; }
function shadowAll(g) { g.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } }); return g; }

function wheel(r, w, m = M.rubber()) {
  const g = new THREE.Group();
  const tyre = cyl(r, r, w, m, 20); tyre.rotation.x = Math.PI / 2; g.add(tyre);
  const hub = cyl(r * 0.45, r * 0.45, w * 1.04, M.darkSteel(), 12); hub.rotation.x = Math.PI / 2; g.add(hub);
  return g;
}

// Ground status disc (colour = state of the twin).
function statusDisc(radius, color) {
  spriteTex = spriteTex || softSprite();
  const m = new THREE.Mesh(new THREE.CircleGeometry(radius, 32),
    new THREE.MeshBasicMaterial({ color, map: spriteTex, transparent: true, opacity: 0.85, depthWrite: false, blending: THREE.AdditiveBlending }));
  m.rotation.x = -Math.PI / 2; m.position.y = 0.6; m.renderOrder = 2;
  return m;
}

function headBeam(len = 34, width = 10) {
  // A soft cone of light in front of the vehicle, visible at night only.
  const geo = new THREE.ConeGeometry(width, len, 16, 1, true);
  geo.translate(0, -len / 2, 0); geo.rotateZ(Math.PI / 2);
  const mat = glow('#ffe7b0', 0.16);
  mat.map = null; mat.side = THREE.DoubleSide;
  const m = new THREE.Mesh(geo, mat);
  m.renderOrder = 3;
  return m;
}

// ------------------------------------------------------------------ mobile fleet
// x = forward (heading direction after rotation), y = up, z = left/right.
export function haulTruck(bodyColor = '#d4824a', { water = false, small = false } = {}) {
  const k = small ? 0.85 : 1;
  const g = new THREE.Group();
  const frame = box(17 * k, 2.2, 4.4 * k, M.darkSteel()); at(frame, 0, 3.4, 0); g.add(frame);
  // wheels: front pair, rear duals
  for (const side of [-1, 1]) {
    g.add(at(wheel(2.9 * k, 2.0 * k), 6.2 * k, 2.9 * k, side * 3.3 * k));
    g.add(at(wheel(2.9 * k, 2.0 * k), -4.4 * k, 2.9 * k, side * 2.6 * k));
    g.add(at(wheel(2.9 * k, 2.0 * k), -4.4 * k, 2.9 * k, side * 4.6 * k));
  }
  // front deck, engine hood, radiator, cab, ladder
  const deck = box(4.2 * k, 1.0, 9.8 * k, M.catYellow()); at(deck, 7.0 * k, 6.6, 0); g.add(deck);
  const hood = box(4.6 * k, 3.2, 3.6 * k, M.catYellow()); at(hood, 6.6 * k, 4.8, 0); g.add(hood);
  const grille = box(0.5, 2.6, 3.2 * k, M.darkSteel()); at(grille, 8.95 * k, 4.6, 0); g.add(grille);
  const cab = box(3.0 * k, 2.8, 2.8 * k, M.catYellow()); at(cab, 7.3 * k, 8.5, -2.9 * k); g.add(cab);
  const win = box(3.05 * k, 1.4, 2.85 * k, M.glass()); at(win, 7.3 * k, 8.9, -2.9 * k); g.add(win);
  const rail = box(0.3, 1.0, 9.8 * k, M.darkSteel()); at(rail, 9.0 * k, 7.6, 0); g.add(rail);
  // head and tail lights
  const hl = emissive('#fff2cf', 3);
  for (const side of [-1, 1]) { const l = box(0.4, 0.7, 1.1, hl); at(l, 9.05 * k, 5.6, side * 2.2 * k); g.add(l); }
  const tl = emissive('#ff3b2f', 2.5);
  for (const side of [-1, 1]) { const l = box(0.3, 0.6, 0.8, tl); at(l, -8.6 * k, 3.6, side * 2.0 * k); g.add(l); }
  const beam = headBeam(40 * k, 9 * k); at(beam, 9.2 * k, 3.0, 0); g.add(beam);

  // dump body pivots on the rear axle
  const bedPivot = new THREE.Group(); at(bedPivot, -7.6 * k, 5.0, 0); g.add(bedPivot);
  const bodyMat = std(bodyColor, { roughness: 0.5, metalness: 0.35, unique: true });
  let load = null;
  if (water) {
    const tank = cyl(2.8 * k, 2.8 * k, 12.5 * k, std('#dfe6ea', { roughness: 0.3, metalness: 0.5 }), 20);
    tank.rotation.z = Math.PI / 2; at(tank, 6.4 * k, 3.2, 0); bedPivot.add(tank);
    const band = cyl(2.85 * k, 2.85 * k, 1.2, bodyMat, 20); band.rotation.z = Math.PI / 2; at(band, 6.4 * k, 3.2, 0); bedPivot.add(band);
  } else {
    const floor = box(13.2 * k, 0.8, 6.4 * k, M.darkSteel()); at(floor, 6.6 * k, 0.6, 0); bedPivot.add(floor);
    for (const side of [-1, 1]) {
      const wall = box(13.2 * k, 3.6, 0.5, bodyMat); at(wall, 6.6 * k, 2.6, side * 3.2 * k); bedPivot.add(wall);
    }
    const front = box(0.6, 4.4, 6.9 * k, bodyMat); at(front, 13.0 * k, 3.0, 0); bedPivot.add(front);
    const canopy = box(3.6 * k, 0.5, 7.4 * k, bodyMat); at(canopy, 14.6 * k, 5.0, 0); bedPivot.add(canopy);
    // payload: a rocky heap
    const lg = new THREE.IcosahedronGeometry(1, 1);
    const p = lg.attributes.position;
    for (let i = 0; i < p.count; i++) { const s = 0.85 + ((Math.sin(i * 12.9898) * 43758.5453) % 1 + 1) % 1 * 0.3; p.setXYZ(i, p.getX(i) * s, Math.max(0, p.getY(i)) * s, p.getZ(i) * s); }
    lg.computeVertexNormals();
    load = new THREE.Mesh(lg, std('#8a5a34', { roughness: 1, unique: true, flatShading: true }));
    load.scale.set(6.2 * k, 3.4, 2.9 * k); at(load, 6.4 * k, 1.4, 0); load.castShadow = true;
    bedPivot.add(load);
  }
  const ring = statusDisc(15 * k, bodyColor); g.add(ring);
  shadowAll(bedPivot);
  g.userData.parts = { bed: bedPivot, bodyMat, load, ring, beam };
  return g;
}

export function lightVehicle() {
  const g = new THREE.Group();
  const body = box(5.2, 1.4, 2.2, M.white()); at(body, 0, 1.6, 0); g.add(body);
  const cab = box(2.4, 1.2, 2.1, M.white()); at(cab, 0.6, 2.8, 0); g.add(cab);
  const win = box(2.45, 0.7, 2.15, M.glass()); at(win, 0.6, 3.0, 0); g.add(win);
  for (const x of [-1.7, 1.7]) for (const z of [-1.1, 1.1]) g.add(at(wheel(0.65, 0.5), x, 0.65, z));
  // buggy whip and amber beacon — compulsory in the pit
  const whip = box(0.08, 4.5, 0.08, M.red()); at(whip, -2.4, 4.6, 0.9); g.add(whip);
  const bm = emissive('#ffae2a', 6); nightMats[nightMats.length - 1].blink = Math.random() * 6;
  const beacon = box(0.5, 0.5, 0.5, bm); at(beacon, 0.6, 3.75, 0); g.add(beacon);
  const beam = headBeam(18, 4); at(beam, 2.7, 1.3, 0); g.add(beam);
  g.userData.parts = {};
  return g;
}

export function person() {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.45, 1.1, 4, 8), std('#ff9b1a', { emissive: '#3a1c00', roughness: 0.6 }));
  at(body, 0, 1.1, 0); body.castShadow = true; g.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.32, 10, 8), std('#f4f4f4')); at(head, 0, 2.15, 0); g.add(head);
  const marker = statusDisc(5, '#f5d000'); g.add(marker);
  const ring = new THREE.Mesh(new THREE.RingGeometry(9, 11, 32), new THREE.MeshBasicMaterial({ color: '#e5534b', side: THREE.DoubleSide, transparent: true, opacity: 0.85, depthWrite: false }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.8; ring.visible = false; g.add(ring);
  g.userData.parts = { ring };
  return g;
}

export function shovel(isShovel = true) {
  const g = new THREE.Group();
  if (isShovel) {
    // Hitachi EX3600-6 front shovel
    for (const side of [-1, 1]) {
      const track = box(14, 2.8, 3.2, M.darkSteel()); at(track, 0, 1.4, side * 4.4); g.add(track);
      const pads = box(14.4, 0.6, 3.4, M.rubber()); at(pads, 0, 0.3, side * 4.4); g.add(pads);
    }
    const car = box(7, 1.8, 6, M.darkSteel()); at(car, 0, 3.4, 0); g.add(car);
    const house = new THREE.Group(); at(house, 0, 4.3, 0); g.add(house);
    const body = box(11, 4.4, 8.4, M.hitachi()); at(body, -1.6, 2.4, 0); house.add(body);
    const cw = box(2.4, 3.4, 8.4, M.darkSteel()); at(cw, -7.6, 2.0, 0); house.add(cw);
    const engine = box(5, 1.6, 6.6, M.hitachi()); at(engine, -3.5, 5.4, 0); house.add(engine);
    const cab = box(2.8, 3.0, 2.8, M.white()); at(cab, 3.4, 6.0, -2.6); house.add(cab);
    const cw2 = box(2.85, 1.4, 2.85, M.glass()); at(cw2, 3.4, 6.5, -2.6); house.add(cw2);
    const lampM = emissive('#fff4d6', 4);
    for (const z of [-3.5, 3.5]) { const lamp = box(0.6, 0.6, 0.6, lampM); at(lamp, 4.8, 4.8, z); house.add(lamp); }
    // boom + stick + bucket (front shovel geometry)
    const boom = new THREE.Group(); at(boom, 3.8, 3.2, 0); house.add(boom);
    const b1 = box(10.5, 1.8, 2.4, M.hitachi()); b1.position.set(5, 0, 0); boom.add(b1); boom.rotation.z = 0.62;
    const stick = new THREE.Group(); at(stick, 10, 0, 0); boom.add(stick);
    const s1 = box(9, 1.4, 2.0, M.hitachi()); s1.position.set(3.8, 0, 0); stick.add(s1); stick.rotation.z = -1.5;
    const bucket = new THREE.Group(); at(bucket, 8.5, 0, 0); stick.add(bucket);
    const bk = box(3.8, 4.2, 5.6, M.darkSteel()); bk.position.set(1.4, -0.6, 0); bucket.add(bk);
    const lip = box(0.5, 0.8, 5.8, M.steel()); lip.position.set(3.4, -2.6, 0); bucket.add(lip);
    bucket.rotation.z = 0.9;
    const beam = headBeam(34, 12); at(beam, 5.5, 1.0, 0); house.add(beam);
    shadowAll(g);
    g.userData.parts = { house, boom, stick, bucket };
    return g;
  }
  // CAT 993K wheel loader
  const yellow = M.catYellow();
  const rear = box(7, 3.4, 4.8, yellow); at(rear, -3.2, 4.4, 0); g.add(rear);
  const front = box(4.6, 2.6, 4.4, yellow); at(front, 2.6, 4.0, 0); g.add(front);
  const cab = box(2.6, 2.8, 3.0, yellow); at(cab, -0.6, 7.4, 0); g.add(cab);
  const win = box(2.65, 1.4, 3.05, M.glass()); at(win, -0.6, 7.8, 0); g.add(win);
  for (const x of [-4.2, 2.8]) for (const z of [-3.2, 3.2]) g.add(at(wheel(2.3, 1.6), x, 2.3, z));
  const house = new THREE.Group(); at(house, 3.8, 3.2, 0); g.add(house);
  const arms = box(6, 1.0, 3.6, yellow); arms.position.set(3, 0.8, 0); house.add(arms);
  const bucket = box(2.6, 2.8, 6.2, M.darkSteel()); bucket.position.set(6.4, 0.2, 0); house.add(bucket);
  const lampM = emissive('#fff4d6', 4);
  const lamp = box(0.5, 0.5, 3.4, lampM); at(lamp, 0.8, 8.9, 0); g.add(lamp);
  const beam = headBeam(28, 9); at(beam, 6, 1.5, 0); g.add(beam);
  shadowAll(g);
  g.userData.parts = { house, loader: true };
  return g;
}

export function drillRig() {
  const g = new THREE.Group();
  for (const side of [-1, 1]) { const t = box(9, 2.0, 2.0, M.darkSteel()); at(t, 0, 1.0, side * 2.6); g.add(t); }
  const deck = box(10, 2.4, 6, std('#e3dfd3', { roughness: 0.55 })); at(deck, 0, 3.2, 0); g.add(deck);
  const cab = box(2.4, 2.6, 2.4, std('#e3dfd3', { roughness: 0.55 })); at(cab, 2.8, 5.6, -1.7); g.add(cab);
  const cw = box(2.45, 1.2, 2.45, M.glass()); at(cw, 2.8, 6.0, -1.7); g.add(cw);
  const mastPivot = new THREE.Group(); at(mastPivot, 4.6, 4.4, 0.8); g.add(mastPivot);
  const mast = box(1.4, 22, 1.4, std('#c9362a', { roughness: 0.5, metalness: 0.3 })); mast.position.y = 11; mastPivot.add(mast);
  const rod = cyl(0.25, 0.25, 21, M.steel(), 8); rod.position.set(0.9, 10.5, 0); mastPivot.add(rod);
  const lampM = emissive('#fff4d6', 4);
  const lamp = box(0.6, 0.6, 0.6, lampM); at(lamp, 0, 21.5, 0.8); mastPivot.add(lamp);
  shadowAll(g);
  g.userData.parts = { mast: mastPivot };
  return g;
}

// ------------------------------------------------------------------ plant
let cladTex = null, cladBlue = null, winTex = null;
function cladMat(color = 'grey') {
  if (color === 'blue') { cladBlue = cladBlue || claddingTexture([92, 128, 168]); return std('#ffffff', { map: cladBlue, roughness: 0.55, metalness: 0.35 }); }
  cladTex = cladTex || claddingTexture();
  return std('#ffffff', { map: cladTex, roughness: 0.55, metalness: 0.35 });
}
function windowMat() {
  winTex = winTex || windowsTexture();
  const m = new THREE.MeshStandardMaterial({ color: '#2a3138', map: winTex, emissive: '#ffd9a0', emissiveMap: winTex, emissiveIntensity: 0, roughness: 0.25, metalness: 0.4, transparent: true, alphaTest: 0.01 });
  nightMats.push({ mat: m, base: 1.6 });
  return m;
}
// A clad industrial building with a band of windows and a pitched roof edge.
export function building(w, h, d, { color = 'grey', windows = true, roof = '#6b7178' } = {}) {
  const g = new THREE.Group();
  const walls = box(w, h, d, cladMat(color)); walls.position.y = h / 2; g.add(walls);
  const r = box(w + 1.2, 1.2, d + 1.2, std(roof, { roughness: 0.6, metalness: 0.5 })); r.position.y = h + 0.6; g.add(r);
  if (windows) {
    const wm = windowMat();
    for (const side of [-1, 1]) {
      const p = new THREE.Mesh(new THREE.PlaneGeometry(w * 0.9, Math.min(h * 0.4, 12)), wm);
      p.position.set(0, h * 0.62, side * (d / 2 + 0.15)); if (side < 0) p.rotation.y = Math.PI; g.add(p);
    }
  }
  return g;
}

export function lightMast(height = 34) {
  // Pit/plant lighting tower: emissive lamp bank + a soft pool of light.
  const g = new THREE.Group();
  const pole = cyl(0.5, 0.9, height, M.steel(), 8); pole.position.y = height / 2; g.add(pole);
  const lamp = box(4.5, 1.6, 1.2, emissive('#fff1cf', 5)); lamp.position.set(0, height, 0); g.add(lamp);
  const pool = new THREE.Mesh(new THREE.CircleGeometry(70, 32), glow('#ffdca0', 0.32));
  pool.rotation.x = -Math.PI / 2; pool.position.y = -height + 1.2; lamp.add(pool);
  const halo = new THREE.Mesh(new THREE.PlaneGeometry(26, 26), glow('#fff0c8', 0.75));
  halo.position.set(0, 0, 0.8); lamp.add(halo);
  g.userData.halo = halo;
  return g;
}

export function latticeTower(h = 46) {
  const g = new THREE.Group();
  const m = std('#9aa3aa', { roughness: 0.5, metalness: 0.7 });
  for (const [x, z] of [[-3, -3], [3, -3], [3, 3], [-3, 3]]) {
    const leg = box(0.5, h, 0.5, m); leg.position.set(x * 0.55, h / 2, z * 0.55); leg.rotation.set(z * 0.012, 0, -x * 0.012); g.add(leg);
  }
  for (let y = 6; y < h; y += 7) { const ring = box(4.2 - y / h * 1.6, 0.3, 4.2 - y / h * 1.6, m); ring.position.y = y; g.add(ring); }
  const arm = box(22, 0.8, 1, m); arm.position.y = h - 3; g.add(arm);
  const arm2 = box(16, 0.8, 1, m); arm2.position.y = h - 9; g.add(arm2);
  const red = emissive('#ff3b2f', 3); nightMats[nightMats.length - 1].blink = Math.random() * 6;
  const beacon = box(0.8, 0.8, 0.8, red); beacon.position.y = h + 0.6; g.add(beacon);
  return g;
}

export function sag(radius = 16, length = 16, color = '#c87533') {
  const g = new THREE.Group();
  const shell = cyl(radius, radius, length, std(color, { roughness: 0.4, metalness: 0.55 }), 36);
  shell.rotation.z = Math.PI / 2; g.add(shell);
  const gear = cyl(radius * 1.08, radius * 1.08, 1.6, M.darkSteel(), 36); gear.rotation.z = Math.PI / 2; gear.position.x = length * 0.32; g.add(gear);
  for (const s of [-1, 1]) { const tr = cyl(radius * 0.38, radius * 0.38, 4, M.steel(), 20); tr.rotation.z = Math.PI / 2; tr.position.x = s * (length / 2 + 2); g.add(tr); }
  const stripe = box(length * 1.01, 1.4, radius * 0.25, M.darkSteel()); stripe.position.y = radius; g.add(stripe);
  return { group: g, spinner: g };
}

// Economy mode (software rendering): swap PBR materials for Lambert ones,
// keeping colour, maps, emissive and transparency; the night-light registry
// follows the swap.
const lambertCache = new Map();
export function toLambert(root) {
  root.traverse((o) => {
    if (!o.isMesh && !o.isInstancedMesh) return;
    const conv = (m) => {
      if (!m || !m.isMeshStandardMaterial) return m;
      if (lambertCache.has(m)) return lambertCache.get(m);
      const l = new THREE.MeshLambertMaterial({
        color: m.color, map: m.map, vertexColors: m.vertexColors, emissive: m.emissive, emissiveMap: m.emissiveMap,
        emissiveIntensity: m.emissiveIntensity, transparent: m.transparent, opacity: m.opacity, side: m.side,
        depthWrite: m.depthWrite, alphaTest: m.alphaTest, flatShading: m.flatShading,
        polygonOffset: m.polygonOffset, polygonOffsetFactor: m.polygonOffsetFactor, polygonOffsetUnits: m.polygonOffsetUnits,
      });
      lambertCache.set(m, l);
      for (const n of nightMats) if (n.mat === m) n.mat = l;
      return l;
    };
    o.material = Array.isArray(o.material) ? o.material.map(conv) : conv(o.material);
  });
  return root;
}
// Materials whose colour the app changes at run time must stay reachable.
export function lambertOf(m) { return lambertCache.get(m) || m; }
