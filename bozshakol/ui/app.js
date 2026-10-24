// Bozshakol 3D control room. Every number on this page is read from the
// Eclipse Ditto twins of the OpenEgiz platform (through the /ditto proxy of
// this nginx); scenario changes are written back to the control twin.
import * as THREE from './vendor/three/three.module.min.js';
import { createEnv, detectStyle } from './js/env.js';
import * as MD from './js/models.js';
import * as T3 from './js/terrain.js';
import { softSprite } from './js/textures.js';
import { createTour } from './js/tour.js';

const API = './ditto/api/2';
const NS = 'kz.bozshakol';
const POLL_MS = 2000;
const VZ = 1.25;                       // vertical exaggeration of the pit
const GRAFANA = new URLSearchParams(location.search).get('grafana') ||
  `${location.protocol}//${location.hostname}:3000`;

const S = {
  site: null, catalog: [], byId: {}, labels: {}, defaults: {}, presets: {},
  t: {}, hist: {}, selected: null, follow: false, lastOk: 0, firstData: false,
  prevBlasts: null, prevBlockState: {},
};

// ---------------------------------------------------------------- helpers
const $ = (s) => document.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const v = (name, f, d = undefined) => { const x = S.t[name]?.[f]; return x === undefined ? d : x; };
const num = (x, n = 0) => (x === undefined || x === null || Number.isNaN(+x)) ? '—' : (+x).toLocaleString('ru-RU', { minimumFractionDigits: n, maximumFractionDigits: n });
const cnum = (x, n = 0) => (Math.abs(+x) >= 10000 ? num(+x / 1000, Math.abs(+x) >= 100000 ? 0 : 1) + 'k' : num(x, Math.abs(+x) >= 1000 ? 0 : n));
const P = (x, y, z) => new THREE.Vector3(x, z * VZ, -y);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function api(path, opts = {}) {
  const r = await fetch(API + path, { cache: 'no-store', ...opts });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.status === 204 ? null : r.json();
}

async function setControl(values) {
  const features = {};
  for (const [k, val] of Object.entries(values)) features[k] = { properties: { value: val } };
  try {
    await api(`/things/${NS}:control`, { method: 'PATCH', headers: { 'Content-Type': 'application/merge-patch+json' }, body: JSON.stringify({ features }) });
  } catch (e) {
    for (const [k, val] of Object.entries(values)) {
      await api(`/things/${NS}:control/features/${k}/properties/value`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(val) });
    }
  }
  poll();
}

// ---------------------------------------------------------------- colours
const DRIVING = new Set(['to_loader', 'hauling', 'to_fuel', 'to_workshop', 'to_park', 'to_reserve', 'towing']);   // haul-truck states in motion
const TRUCK_COLORS = {
  no_fuel: '#e5534b', hauling: '#d4824a', to_loader: '#5aa6e8', queue_loader: '#e6b13a', queue_dump: '#e6b13a', spotting: '#c9d36a',
  loading: '#9ad36a', dumping: '#c58cf0', to_fuel: '#7fd6d0', refueling: '#7fd6d0', to_workshop: '#a0a0a0',
  in_workshop: '#7a7a7a', breakdown: '#e5534b', towing: '#e5534b', standby: '#6b7480', parked: '#4b525b',
  to_park: '#6b7480', to_reserve: '#6b7480', idle: '#6b7480',
};
const TRUCK_LEGEND = [['груженый рейс', 'hauling'], ['порожний', 'to_loader'], ['очередь', 'queue_loader'],
  ['погрузка', 'loading'], ['разгрузка', 'dumping'], ['АЗС', 'refueling'], ['отказ', 'breakdown'], ['ТО/резерв', 'in_workshop']];
const BLOCK_COLORS = { planned: '#56606b', drilling: '#4f7fb0', drilled: '#3f9bd0', charging: '#d08a3f', charged: '#e86b2c',
  blasted: '#a35fd0', mining: '#58b368', depleted: '#30363c' };
const ROAD_COLORS = { open: '#b9ab94', restricted: '#e6b13a', closed: '#d0453a' };
const LEVEL_COLORS = { green: '#4fbf7a', amber: '#e6b13a', red: '#e5534b' };

// ---------------------------------------------------------------- three.js setup
const canvas = $('#scene');
let renderer = null, env = null, scene, camera, raycaster, pickables = [];
let webgl = true;
const STYLE = detectStyle();
const DIORAMA = STYLE === 'diorama';
MD.setStyle(STYLE);
if (DIORAMA) document.body.classList.add('diorama');
scene = new THREE.Scene();
// A narrower lens in the diorama: less perspective, closer to an isometric miniature.
camera = new THREE.PerspectiveCamera(DIORAMA ? 30 : 40, 1, 3, 120000);
const LENS = DIORAMA ? Math.tan((40 / 2) * Math.PI / 180) / Math.tan((30 / 2) * Math.PI / 180) : 1;
raycaster = new THREE.Raycaster();
try {
  env = createEnv({ canvas, scene, camera, style: STYLE });
  renderer = env.renderer;
  window.__lowQuality = !env.high;
  if (!env.high) document.body.classList.add('low');
} catch (e) {
  console.warn('WebGL unavailable', e);
  webgl = false;
  $('#noWebgl').classList.remove('hidden');
}

const mat = (c, o = {}) => MD.std(c, o);
const box = (w, h, d, c) => MD.box(w, h, d, typeof c === 'string' ? mat(c) : c);
const cyl = (rt, rb, h, c, seg = 24) => MD.cyl(rt, rb, h, typeof c === 'string' ? mat(c) : c, seg);

// Orbit camera (own implementation: rotate / pan / zoom, mouse + touch).
// `goal` is where the user steers; `orbit` eases towards it every frame, so
// rotating, panning and zooming glide instead of jumping.
const orbit = { target: new THREE.Vector3(1200, -80, 0), dist: 5200, theta: -0.55, phi: 0.95 };
const goal = { target: orbit.target.clone(), dist: orbit.dist, theta: orbit.theta, phi: orbit.phi };
const syncGoal = () => { goal.target.copy(orbit.target); goal.dist = orbit.dist; goal.theta = orbit.theta; goal.phi = orbit.phi; };
function dampCamera(dt) {
  const k = 1 - Math.exp(-dt * 8);
  goal.phi = Math.min(DIORAMA ? 1.38 : 1.5, Math.max(0.1, goal.phi));
  goal.dist = Math.min(DIORAMA ? 22000 : 16000, Math.max(60, goal.dist));
  orbit.target.lerp(goal.target, k);
  orbit.dist += (goal.dist - orbit.dist) * k;
  orbit.theta += (goal.theta - orbit.theta) * k;
  orbit.phi += (goal.phi - orbit.phi) * k;
}
function placeCamera() {
  const o = orbit;
  o.phi = Math.min(1.5, Math.max(0.1, o.phi));
  o.dist = Math.min(DIORAMA ? 22000 : 16000, Math.max(60, o.dist));
  camera.position.set(o.target.x + o.dist * Math.sin(o.phi) * Math.sin(o.theta), o.target.y + o.dist * Math.cos(o.phi),
    o.target.z + o.dist * Math.sin(o.phi) * Math.cos(o.theta));
  camera.lookAt(o.target);
}
const VIEWS = {
  overview: { t: P(1900, -250, -60), dist: 4700, theta: -0.78, phi: 1.2 },
  pit: { t: P(-50, 200, -130), dist: 1950, theta: 0.12, phi: 0.98 },
  plant: { t: P(4180, -640, 0), dist: 1150, theta: -0.62, phi: 1.04 },
  east: { t: P(2600, -1580, -50), dist: 1350, theta: 0.35, phi: 0.95 },
  top: { t: P(1700, -150, 0), dist: 7200, theta: 0, phi: 0.12 },
};
if (DIORAMA) {
  // The whole block in frame, seen from a three-quarter isometric angle.
  VIEWS.overview = { t: P(1850, -150, -160), dist: 12800, theta: -0.62, phi: 0.92 };
  for (const k of ['pit', 'plant', 'top', 'east']) VIEWS[k].dist *= LENS;
  VIEWS.top.dist = 11500;
}
let tween = null;
function flyTo(to, dur = 1600) {
  if (typeof to === 'string') { setView(to, dur); return; }
  const d = to.theta - orbit.theta;
  const theta = orbit.theta + Math.atan2(Math.sin(d), Math.cos(d));
  tween = { from: { ...orbit, target: orbit.target.clone() }, to: { t: to.t.clone(), dist: to.dist * LENS, theta, phi: to.phi }, t0: performance.now(), dur };
}
function setView(name, dur = 1100) {
  const vw = VIEWS[name];
  if (!vw) return;
  const d = vw.theta - orbit.theta;
  tween = { from: { ...orbit, target: orbit.target.clone() }, to: { ...vw, theta: orbit.theta + Math.atan2(Math.sin(d), Math.cos(d)) }, t0: performance.now(), dur };
  document.querySelectorAll('.views button').forEach((b) => b.classList.toggle('active', b.dataset.view === name));
}
let lastInput = performance.now();
(function controls() {
  let drag = null;
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, y: e.clientY, b: e.button, shift: e.shiftKey, moved: 0 }; canvas.setPointerCapture(e.pointerId); lastInput = performance.now(); });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY; drag.moved += Math.abs(dx) + Math.abs(dy);
    if (drag.b === 2 || drag.shift) {
      const k = orbit.dist / (900 * LENS);
      const right = new THREE.Vector3(Math.cos(orbit.theta), 0, -Math.sin(orbit.theta));
      const fwd = new THREE.Vector3(-Math.sin(orbit.theta), 0, -Math.cos(orbit.theta));
      goal.target.addScaledVector(right, -dx * k).addScaledVector(fwd, dy * k);
    } else {
      goal.theta -= dx * 0.005; goal.phi -= dy * 0.005;
    }
    if (drag.moved > 5) { S.follow = false; $('#followBtn').classList.remove('active'); tween = null; tour?.userInterrupt(); }
    lastInput = performance.now();
  });
  canvas.addEventListener('pointerup', (e) => {
    if (drag && drag.moved < 5 && drag.b === 0) pick(e);
    drag = null;
  });
  canvas.addEventListener('wheel', (e) => { e.preventDefault(); goal.dist *= Math.exp(e.deltaY * 0.0012); tween = null; tour?.userInterrupt(); lastInput = performance.now(); }, { passive: false });
  window.addEventListener('keydown', () => { lastInput = performance.now(); });
})();

function pick(e) {
  const r = canvas.getBoundingClientRect();
  const m = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(m, camera);
  const hit = raycaster.intersectObjects(pickables, true)[0];
  if (!hit) return;
  let o = hit.object;
  while (o && !o.userData.twin) o = o.parent;
  if (o) select(o.userData.twin);
}

// ---------------------------------------------------------------- static scene
const objs = {};      // twin name -> Object3D
const tags = {};      // key -> {el, pos(fn), show(fn)}
const roadMats = {};
let terrainY = 0;

function addTag(key, html, posFn, opts = {}) {
  const t = el('div', 'tag' + (opts.cls ? ' ' + opts.cls : ''), html);
  if (opts.twin) t.addEventListener('click', () => select(opts.twin));
  $('#labels').appendChild(t);
  tags[key] = { el: t, pos: posFn, show: opts.show || (() => $('#lyrLabels').checked), twin: opts.twin, prio: opts.prio || 1, w: 0, h: 0, vis: false };
  return tags[key];
}

function buildGround(pit) {
  T3.buildGround(scene, pit, VZ, S.site.layout, !env?.high, DIORAMA);
}

function buildPit(pit) {
  const { pitMesh } = T3.buildPit(scene, pit, P, VZ);
  pitMesh.userData.twin = 'pit-central';
  pickables.push(pitMesh);
  // Lighting masts on the pit rim (they light up for the night shift).
  for (let i = 0; i < 9; i++) {
    const th = (i / 9) * Math.PI * 2 + 0.2;
    const m = MD.lightMast(36);
    m.position.copy(P((pit.a + 45) * Math.cos(th), (pit.b + 45) * Math.sin(th), 0));
    scene.add(m); masts.push(m);
  }
  for (const [x, y] of [[-420, 120], [380, -160], [60, 260]]) {
    const m = MD.lightMast(24);
    m.position.copy(P(x, y, -pit.bench_h * pit.n));
    scene.add(m); masts.push(m);
  }
}
const masts = [];

function buildRoads(layout) {
  const berm = T3.bermMaterial();
  const bodyMat = new THREE.MeshStandardMaterial({ color: DIORAMA ? '#a58e6e' : '#8f7d64', roughness: 0.95, side: THREE.DoubleSide });
  const benchH = layout.pit?.bench_h || 15;
  for (const e of layout.edges) {
    if (!roadMats[e.road]) roadMats[e.road] = T3.roadMaterial(ROAD_COLORS.open);
    const w = e.road === 'road-faces' ? 14 : e.road === 'road-ramp' ? 26 : 22;
    const lift = e.road === 'road-ramp' ? 1.6 : 0.8;
    const m = new THREE.Mesh(T3.roadGeometry(e.pts, w, lift, P), roadMats[e.road]);
    m.receiveShadow = true;
    m.userData.twin = e.road;
    scene.add(m); pickables.push(m);
    if (e.pts.some((q) => Math.abs(q[2]) > 0.3)) {
      const body = new THREE.Mesh(T3.roadBodyGeometry(e.pts, w + (e.road !== 'road-faces' ? 8 : 0), P, benchH), bodyMat);
      body.receiveShadow = true; body.castShadow = env?.high;
      scene.add(body);
    }
    if (e.road !== 'road-faces') {
      for (const s of [-1, 1]) {
        const b = new THREE.Mesh(T3.bermGeometry(e.pts, s * (w / 2 + 3.5), lift - 0.7, P), berm);
        b.castShadow = true; b.receiveShadow = true;
        scene.add(b);
      }
    }
  }
}

function placeAt(obj, f, lift = 0) { const p = P(f[0], f[1], f[2]); obj.position.set(p.x, p.y + lift, p.z); return obj; }

function facility(name, twin, builder, label) {
  const f = S.site.layout.facilities[name];
  const g = new THREE.Group();
  builder(g);
  placeAt(g, f);
  // Facilities set above the steppe (the crusher's tipping pad, the clay plant)
  // stand on an earth pad down to the ground; heaps carry their own shape.
  const PAD = { crusher: [70, 55], clay_plant: [80, 60], lg: [150, 150] };
  if (f[2] > 0.5 && PAD[name]) {
    const [ra, rb] = PAD[name], h = f[2] * VZ;
    const pad = new THREE.Mesh(new THREE.CylinderGeometry(1, 1 + 1.5 * f[2] / ra, h, 32),
      new THREE.MeshStandardMaterial({ color: DIORAMA ? '#a58e6e' : '#8f7d64', roughness: 0.95 }));
    pad.scale.set(ra, 1, rb); pad.position.y = -h / 2;
    pad.receiveShadow = true;
    g.add(pad);
  }
  g.userData.twin = twin;
  scene.add(g); pickables.push(g);
  objs[twin] = objs[twin] || g;
  if (label) addTag('fac-' + name, label, () => g.position.clone().add(new THREE.Vector3(0, 70, 0)), { twin, prio: 2 });
  return g;
}

function pile(color, seg = 48) {
  // Natural stockpile: a cone with a noisy outline and flat-shaded facets.
  const geo = new THREE.ConeGeometry(1, 1, seg, 6);
  const p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), z = p.getZ(i), y = p.getY(i);
    const r = Math.hypot(x, z);
    if (r < 1e-4) continue;
    const th = Math.atan2(z, x);
    const k = 1 + 0.06 * Math.sin(th * 5 + y * 3) + 0.04 * Math.sin(th * 11);
    p.setXYZ(i, x * k, y, z * k);
  }
  geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, mat(color, { roughness: 1, flatShading: true }));
  m.castShadow = true; m.receiveShadow = true;
  return m;
}

const dyn = {};   // animated bits keyed by purpose
function buildPlant() {
  const F = S.site.layout.facilities;
  // Gyratory crusher on its ROM pad: concrete tipping wall, crusher house, dump pocket.
  facility('crusher', 'gc-01', (g) => {
    const pad = box(170, 10 * VZ, 130, mat('#a39270', { roughness: 1 })); pad.position.y = -5 * VZ; g.add(pad);
    const wall = box(10, 14, 70, MD.M.concrete()); wall.position.set(-26, 7, 0); g.add(wall);
    const house = MD.building(46, 40, 42, { color: 'grey' }); house.position.set(4, 0, 0); g.add(house);
    const lower = box(48, 10, 44, MD.M.concrete()); lower.position.set(4, -4, 0); g.add(lower);
    const hop = cyl(30, 12, 18, MD.M.darkSteel(), 4); hop.position.set(-8, 50, 0); hop.rotation.y = Math.PI / 4; g.add(hop);
    dyn.pocket = cyl(22, 10, 1, mat('#7a5a3a', { roughness: 1, unique: true }), 4); dyn.pocket.position.set(-8, 44, 0); dyn.pocket.rotation.y = Math.PI / 4; g.add(dyn.pocket);
    const mast = MD.lightMast(30); mast.position.set(50, 0, 50); g.add(mast); masts.push(mast);
  }, '<b>ККД-1</b>');
  // Overland conveyor: crusher -> COS, an enclosed gallery on trestles.
  const a = P(...F.crusher), b = P(...F.cos);
  const len = a.distanceTo(b);
  const dir = b.clone().sub(a).normalize();
  const conv = new THREE.Group();
  const gallery = box(len, 4, 6, mat('#a7adb3', { roughness: 0.5, metalness: 0.5 })); gallery.position.y = 14; conv.add(gallery);
  const roofc = box(len, 0.6, 7, mat('#5f6e7b', { roughness: 0.5, metalness: 0.6 })); roofc.position.y = 16.4; conv.add(roofc);
  const legs = Math.floor(len / 90);
  for (let i = 0; i <= legs; i++) { const l = box(1.4, 12, 5, MD.M.steel()); l.position.set(-len / 2 + i * (len / legs), 6, 0); conv.add(l); }
  conv.position.copy(a.clone().add(b).multiplyScalar(0.5));
  conv.rotation.y = Math.atan2(-(b.z - a.z), b.x - a.x);
  conv.userData.twin = 'cv-01'; scene.add(conv); pickables.push(conv); objs['cv-01'] = conv;
  dyn.parcels = new THREE.InstancedMesh(new THREE.BoxGeometry(14, 2.6, 4.2), mat('#7a5232', { roughness: 1 }), 70);
  dyn.convA = a.clone().add(new THREE.Vector3(0, 18, 0)); dyn.convB = b.clone().add(new THREE.Vector3(0, 18, 0));
  scene.add(dyn.parcels);
  addTag('fac-cv', '<b>Конвейер 2,1 км</b>', () => conv.position.clone().add(new THREE.Vector3(0, 40, 0)), { twin: 'cv-01', prio: 1 });
  // Coarse ore stockpile under a stacker tower.
  facility('cos', 'cos-01', (g) => {
    dyn.cos = pile('#7d5b3d'); dyn.cos.scale.set(80, 35, 80); dyn.cos.position.y = 17; g.add(dyn.cos);
    const tower = box(8, 62, 8, MD.M.steel()); tower.position.set(0, 31, 0); g.add(tower);
    const boom = box(70, 3, 4, mat('#a7adb3', { metalness: 0.5, roughness: 0.5 })); boom.position.set(-35, 58, 0); boom.rotation.z = -0.55; g.add(boom);
    const tunnel = box(160, 6, 10, MD.M.concrete()); tunnel.position.set(90, 3, 0); g.add(tunnel);
  }, '<b>Склад КД</b>');
  // Concentrator: a cut-away mill building with the SAG and two ball mills inside.
  facility('sag', 'sag-01', (g) => {
    const glass = mat('#b8c7d2', { transparent: true, opacity: 0.16, roughness: 0.1, metalness: 0.3, depthWrite: false, unique: true });
    const frameM = mat('#5f6e7b', { roughness: 0.5, metalness: 0.6 });
    const W = 150, H = 58, D = 310;
    const shell = box(W, H, D, glass); shell.position.y = H / 2; shell.castShadow = false; g.add(shell);
    for (let x = -W / 2; x <= W / 2; x += W / 4) for (const z of [-D / 2, D / 2]) { const c = box(2.2, H, 2.2, frameM); c.position.set(x, H / 2, z); g.add(c); }
    for (let z = -D / 2; z <= D / 2; z += D / 6) for (const x of [-W / 2, W / 2]) { const c = box(2.2, H, 2.2, frameM); c.position.set(x, H / 2, z); g.add(c); }
    for (const z of [-D / 2, D / 2]) { const beam = box(W, 2.4, 2.4, frameM); beam.position.set(0, H, z); g.add(beam); }
    for (const x of [-W / 2, W / 2]) { const beam = box(2.4, 2.4, D, frameM); beam.position.set(x, H, 0); g.add(beam); }
    const end = MD.building(W, H, 8, { color: 'blue' }); end.position.set(0, 0, D / 2 - 4); g.add(end);
    const floor = box(W, 2, D, MD.M.concrete()); floor.position.y = 1; g.add(floor);
    const s = MD.sag(17, 16, '#c87533'); s.group.position.set(0, 24, 0); g.add(s.group); dyn.sag = s.spinner;
    const ped = box(30, 8, 26, MD.M.concrete()); ped.position.set(0, 4, 0); g.add(ped);
    const crane = box(W - 6, 3, 4, mat('#e6b13a', { roughness: 0.5, metalness: 0.4 })); crane.position.set(0, H - 6, 40); g.add(crane);
  }, '<b>МПСИ 28 МВт</b>');
  dyn.bm = [];
  for (const id of ['bm-01', 'bm-02']) {
    facility(id, id, (g) => {
      const m = MD.sag(9, 28, '#c6874e'); m.group.position.y = 15; g.add(m.group);
      const ped = box(36, 6, 14, MD.M.concrete()); ped.position.y = 3; g.add(ped);
      dyn.bm.push(m.spinner);
    });
  }
  addTag('fac-bm', '<b>ШМ ×2</b>', () => P(...F['bm-02']).add(new THREE.Vector3(0, 50, 0)), { twin: 'bm-01', prio: 1 });
  // Flotation banks: tank cells with froth, walkways and launders.
  dyn.froth = [];
  const frothMat = new THREE.MeshStandardMaterial({ color: '#b9a24a', roughness: 0.35, metalness: 0.2, emissive: '#2b2408' });
  for (const [fac, twin, n, lbl] of [['flot_r', 'fl-r', 8, '<b>Флотация</b>'], ['flot_c', 'fl-c', 6, null]]) {
    facility(fac, twin, (g) => {
      for (let i = 0; i < n; i++) {
        const x = (i - (n - 1) / 2) * 22;
        const c = cyl(9.5, 9.5, 16, MD.M.steel(), 28); c.position.set(x, 8, 0); g.add(c);
        const lip = cyl(10.2, 10.2, 1, MD.M.darkSteel(), 28); lip.position.set(x, 16, 0); g.add(lip);
        const fr = new THREE.Mesh(new THREE.CircleGeometry(9.2, 28), frothMat); fr.rotation.x = -Math.PI / 2; fr.position.set(x, 16.3, 0); g.add(fr);
        const mot = box(3, 4, 3, mat('#3c6e9b', { roughness: 0.5, metalness: 0.4 })); mot.position.set(x, 19, 0); g.add(mot);
        dyn.froth.push(fr);
      }
      const walk = box(n * 22, 0.8, 4, mat('#e6b13a', { roughness: 0.6 })); walk.position.set(0, 17.5, 12); g.add(walk);
      const laund = box(n * 22, 2, 3, MD.M.darkSteel()); laund.position.set(0, 15, -12); g.add(laund);
    }, lbl);
  }
  for (const [fac, twin, r, lbl] of [['th_c', 'th-c', 30, '<b>Сгуститель конц.</b>'], ['th_t', 'th-t', 48, '<b>Сгуститель хвостов</b>']]) {
    facility(fac, twin, (g) => {
      const t = cyl(r, r + 1.5, 9, MD.M.concrete(), 56); t.position.y = 4.5; g.add(t);
      const w = new THREE.Mesh(new THREE.CircleGeometry(r - 1.2, 56), T3.waterMaterial(twin === 'th-c' ? '#3f4a3a' : '#5d6f6a')); w.rotation.x = -Math.PI / 2; w.position.y = 8.6; g.add(w);
      const col = cyl(2.5, 2.5, 14, MD.M.steel(), 12); col.position.y = 7; g.add(col);
      const rake = new THREE.Group(); rake.position.y = 10.5; g.add(rake);
      const bridge = box(r * 2 - 4, 1.6, 3, mat('#e6b13a', { roughness: 0.55 })); bridge.position.x = 0; rake.add(bridge);
      const drive = box(5, 3, 5, MD.M.darkSteel()); drive.position.y = 1.5; rake.add(drive);
      (dyn.rakes = dyn.rakes || []).push(rake);
      if (twin === 'th-t') dyn.tailsWater = w;
    }, lbl);
  }
  // Tailings storage facility: beach, decant pond, perimeter dam.
  facility('tsf', 'tsf-01', (g) => {
    const beach = new THREE.Mesh(new THREE.CircleGeometry(1, 96), mat('#cdbf9b', { roughness: 1 })); beach.scale.set(560, 380, 1); beach.rotation.x = -Math.PI / 2; beach.position.y = 3; beach.receiveShadow = true; g.add(beach);
    const water = new THREE.Mesh(new THREE.CircleGeometry(1, 96), T3.waterMaterial('#4f7584')); water.scale.set(330, 210, 1); water.rotation.x = -Math.PI / 2; water.position.set(80, 3.6, 40); g.add(water);
    const dam = new THREE.Mesh(new THREE.TorusGeometry(1, 0.04, 8, 120), mat('#a58f6a', { roughness: 1 })); dam.scale.set(560, 380, 260); dam.rotation.x = -Math.PI / 2; dam.position.y = 3; dam.castShadow = true; g.add(dam);
    const pipe = box(900, 2, 2, mat('#2d3238', { roughness: 0.6 })); pipe.position.set(0, 4, -385); g.add(pipe);
  }, '<b>Хвостохранилище</b>');
  facility('clay_plant', 'cp-01', (g) => {
    const b1 = MD.building(90, 30, 60, { color: 'blue' }); g.add(b1);
    dyn.scrubber = cyl(8, 8, 30, mat('#c6874e', { roughness: 0.4, metalness: 0.5 })); dyn.scrubber.rotation.z = Math.PI / 2; dyn.scrubber.position.set(0, 38, 0); g.add(dyn.scrubber);
    const st = box(36, 2, 28, MD.M.steel()); st.position.set(0, 31, 0); g.add(st);
  }, '<b>Глинистая фабрика</b>');
  facility('substation', 'ss-220', (g) => {
    const pad = box(110, 1, 80, mat('#9a9a92', { roughness: 1 })); pad.position.y = 0.5; g.add(pad);
    for (let i = 0; i < 3; i++) {
      const t = box(14, 12, 10, mat('#5f6a73', { roughness: 0.5, metalness: 0.5 })); t.position.set(i * 26 - 26, 7, 0); g.add(t);
      for (let f = -2; f <= 2; f++) { const fin = box(0.6, 10, 12, MD.M.darkSteel()); fin.position.set(i * 26 - 26 + f * 2.6, 7, 0); g.add(fin); }
      const bush = cyl(0.8, 1, 6, mat('#d9d4c9'), 8); bush.position.set(i * 26 - 26, 16, 0); g.add(bush);
    }
    for (const x of [-40, 0, 40]) { const gt = MD.latticeTower(26); gt.position.set(x, 0, -28); g.add(gt); }
    dyn.subGlow = new THREE.Mesh(new THREE.SphereGeometry(5, 16, 12), new THREE.MeshBasicMaterial({ color: '#5aa6e8' })); dyn.subGlow.position.set(0, 36, 0); g.add(dyn.subGlow);
  }, '<b>ПС 220 кВ</b>');
  // 220 kV line towards Ekibastuz (north-east): lattice towers and sagging conductors.
  const s0 = P(...F.substation);
  const towerPts = [];
  for (let i = 1; i <= 9; i++) {
    const tw = MD.latticeTower(48);
    tw.position.copy(s0).add(new THREE.Vector3(i * 280, 0, -i * 175));
    tw.rotation.y = 0.56;
    scene.add(tw); towerPts.push(tw.position.clone());
  }
  const wireMat = new THREE.LineBasicMaterial({ color: '#2b2f33', transparent: true, opacity: 0.8 });
  for (const off of [-9, 0, 9]) {
    const pts = [];
    for (let i = 0; i < towerPts.length - 1; i++) {
      const p0 = towerPts[i], p1 = towerPts[i + 1];
      const side = new THREE.Vector3(0.53, 0, 0.848).multiplyScalar(off);
      for (let k = 0; k <= 12; k++) {
        const f = k / 12;
        const p = p0.clone().lerp(p1, f).add(side);
        p.y += 45 - Math.sin(f * Math.PI) * 9;
        pts.push(p);
      }
    }
    scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), wireMat));
  }
  facility('water', 'water-01', (g) => {
    const t = cyl(20, 20, 18, mat('#cfd8dc', { roughness: 0.4, metalness: 0.5 }), 40); t.position.y = 9; g.add(t);
    const rim = cyl(20.4, 20.4, 1.2, mat('#3c6e9b', { roughness: 0.5 }), 40); rim.position.y = 17; g.add(rim);
    const p = cyl(1.4, 1.4, 900, mat('#3c6e9b', { roughness: 0.5, metalness: 0.4 }), 10); p.rotation.z = Math.PI / 2; p.position.set(-450, 3, 0); g.add(p);
    const p2 = cyl(1.4, 1.4, 1600, mat('#3c6e9b', { roughness: 0.5, metalness: 0.4 }), 10); p2.rotation.z = Math.PI / 2; p2.position.set(800, 3, 0); g.add(p2);
  }, '<b>Водовод (канал им. Сатпаева)</b>');
  facility('workshop', 'ws-01', (g) => {
    const b1 = MD.building(150, 34, 70, { color: 'grey', roof: '#7a2e24' }); g.add(b1);
    for (let i = 0; i < 4; i++) { const d = box(28, 26, 1, mat('#3b4148', { metalness: 0.5, roughness: 0.5 })); d.position.set(-52 + i * 35, 13, 35.6); g.add(d); }
    const apron = box(170, 0.6, 90, mat('#8e8a80', { roughness: 1 })); apron.position.set(0, 0.3, 70); apron.receiveShadow = true; g.add(apron);
    const mast = MD.lightMast(28); mast.position.set(80, 0, 70); g.add(mast); masts.push(mast);
  }, '<b>Ремзона</b>');
  facility('fuel', 'fs-01', (g) => {
    const canopy = box(46, 2, 26, MD.M.white()); canopy.position.y = 12; g.add(canopy);
    const stripe = box(46.2, 0.8, 26.2, mat('#d4824a')); stripe.position.y = 11.2; g.add(stripe);
    for (const x of [-18, 18]) for (const z of [-9, 9]) { const c = cyl(0.6, 0.6, 11, MD.M.steel(), 8); c.position.set(x, 5.5, z); g.add(c); }
    for (let i = 0; i < 3; i++) { const t = cyl(6, 6, 26, mat('#d9d4c9', { roughness: 0.4, metalness: 0.4 })); t.rotation.z = Math.PI / 2; t.position.set(-10 + i * 0, 6, -30 - i * 14); g.add(t); }
    for (const x of [-10, 10]) { const pmp = box(2, 3.5, 1.4, mat('#d4824a')); pmp.position.set(x, 1.75, 0); g.add(pmp); }
  }, '<b>АЗС</b>');
  facility('camp', 'site', (g) => {
    for (let i = 0; i < 6; i++) { const b1 = MD.building(60, 12, 18, { color: i % 2 ? 'blue' : 'grey', roof: '#5a6068' }); b1.position.set((i % 3) * 75, 0, Math.floor(i / 3) * 40); g.add(b1); }
    const can = MD.building(70, 9, 30, { color: 'grey', roof: '#7a2e24' }); can.position.set(75, 0, 90); g.add(can);
    const mast = MD.lightMast(20); mast.position.set(-30, 0, 20); g.add(mast); masts.push(mast);
  }, '<b>Вахтовый посёлок</b>');
  facility('dump', 'wd-01', (g) => {
    dyn.dump = T3.terracedHeap(400, 30 * VZ + 8, 3, '#9a9286', 3); dyn.dump.position.y = -30 * VZ; g.add(dyn.dump);
  }, '<b>Северный отвал</b>');
  if (S.site.layout.facilities.dump_e) facility('dump_e', 'wd-02', (g) => {
    dyn.dumpE = T3.terracedHeap(260, 20 * VZ + 6, 2, '#a39a8c', 5); dyn.dumpE.position.y = -20 * VZ; g.add(dyn.dumpE);
  }, '<b>Восточный отвал</b>');
  facility('lg', 'lg-01', (g) => {
    dyn.lg = pile('#8c7356'); dyn.lg.scale.set(140, 26, 140); dyn.lg.position.y = 12; g.add(dyn.lg);
  }, '<b>Склад забаланса</b>');
  facility('radar', 'sr-01', (g) => {
    const tr = box(10, 4, 5, MD.M.white()); tr.position.y = 3; g.add(tr);
    const mastR = box(1.2, 9, 1.2, MD.M.steel()); mastR.position.y = 9.5; g.add(mastR);
    dyn.radarDish = new THREE.Group(); dyn.radarDish.position.y = 14; g.add(dyn.radarDish);
    const dish = cyl(6, 6, 1.2, MD.M.white(), 24); dish.rotation.x = Math.PI / 2.3; dish.position.z = 2; dyn.radarDish.add(dish);
    const solar = box(8, 0.3, 5, MD.M.glass()); solar.position.set(-8, 6, 0); solar.rotation.z = 0.5; g.add(solar);
  }, '<b>Радар бортов</b>');
  facility('weather', 'wx-01', (g) => {
    const pole = box(1.2, 24, 1.2, MD.M.steel()); pole.position.y = 12; g.add(pole);
    dyn.windArrow = new THREE.Group();
    const shaft = box(20, 1.5, 1.5, mat('#e6b13a')); shaft.position.x = 10; dyn.windArrow.add(shaft);
    const head = new THREE.Mesh(new THREE.ConeGeometry(3, 6, 8), mat('#e6b13a')); head.rotation.z = -Math.PI / 2; head.position.x = 22; dyn.windArrow.add(head);
    dyn.windArrow.position.y = 24; g.add(dyn.windArrow);
  }, '<b>Метео</b>');
  // Real-data twins (open datasets + ML): flotation quality analyser, seismic station.
  if (F.qc) facility('qc', 'qc-01', (g) => {
    const cab = box(14, 10, 8, MD.M.white()); cab.position.y = 5; g.add(cab);
    const scr = box(9, 5, 0.4, new THREE.MeshStandardMaterial({ color: '#0d2233', emissive: '#3fb8ff', emissiveIntensity: 0.9 })); scr.position.set(0, 6.5, 4.2); g.add(scr);
    const pipe = cyl(0.8, 0.8, 60, MD.M.steel(), 8); pipe.rotation.z = Math.PI / 2; pipe.position.set(30, 3, 0); g.add(pipe);
    dyn.qcScreen = scr;
  }, '<b>QC-01</b> · данные + ML');
  if (F.seis) facility('seis', 'sm-01', (g) => {
    const hut = box(10, 6, 8, MD.M.white()); hut.position.y = 3; g.add(hut);
    const mast = box(0.8, 26, 0.8, MD.M.steel()); mast.position.set(6, 13, 0); g.add(mast);
    dyn.seisLamp = new THREE.Mesh(new THREE.SphereGeometry(2.2, 12, 8), new THREE.MeshBasicMaterial({ color: '#4fbf7a' }));
    dyn.seisLamp.position.set(6, 27, 0); g.add(dyn.seisLamp);
  }, '<b>SM-01</b> · данные + ML');
  if (F.en) facility('en', 'en-01', (g) => {
    // metering cabinet with a live load bar: height follows the real plant load
    const cab = box(8, 9, 5, MD.M.white()); cab.position.y = 4.5; g.add(cab);
    dyn.enBar = box(3, 1, 3, new THREE.MeshStandardMaterial({ color: '#3fb8ff', emissive: '#3fb8ff', emissiveIntensity: 0.6 }));
    dyn.enBar.position.set(8, 0.5, 0); g.add(dyn.enBar);
  }, '<b>EN-01</b> · энергопрофиль');
  if (F.mwd) facility('mwd', 'mwd-01', (g) => {
    // core-shed style cabin with racks of drill rods and a status screen
    const hut = box(16, 7, 9, MD.M.white()); hut.position.y = 3.5; g.add(hut);
    for (let i = 0; i < 5; i++) { const rod = cyl(0.35, 0.35, 18, MD.M.steel(), 8); rod.rotation.z = Math.PI / 2; rod.position.set(0, 1 + i * 0.8, 7); g.add(rod); }
    dyn.mwdScreen = box(10, 4, 0.4, new THREE.MeshStandardMaterial({ color: '#0d2233', emissive: '#3fb8ff', emissiveIntensity: 0.9 }));
    dyn.mwdScreen.position.set(0, 4.5, -4.7); g.add(dyn.mwdScreen);
  }, '<b>MWD-01</b> · данные + ML');
  // Normative control (ГОСТ): QC laboratory at the plant, power-quality analyser at the substation.
  if (F.lab) facility('lab', 'lab-01', (g) => {
    const b1 = MD.building(46, 12, 22, { color: 'grey', roof: '#3c6e9b' }); g.add(b1);
    const sampler = box(6, 18, 6, MD.M.steel()); sampler.position.set(30, 9, 0); g.add(sampler);
  }, '<b>ОТК</b> · ГОСТ 14180/13170/24598');
  if (F.pq) facility('pq', 'pq-01', (g) => {
    const cab = box(6, 7, 4, MD.M.white()); cab.position.y = 3.5; g.add(cab);
    dyn.pqLamp = new THREE.Mesh(new THREE.SphereGeometry(1.6, 12, 8), new THREE.MeshBasicMaterial({ color: '#4fbf7a' }));
    dyn.pqLamp.position.set(0, 9, 0); g.add(dyn.pqLamp);
  }, '<b>PQ-01</b> · ГОСТ 32144');
  dyn.dust = {};
  for (const id of ['dm-01', 'dm-02', 'dm-03']) {
    facility(id, id, (g) => {
      const pole = box(1.2, 14, 1.2, MD.M.steel()); pole.position.y = 7; g.add(pole);
      const s = new THREE.Mesh(new THREE.SphereGeometry(4, 14, 10), new THREE.MeshBasicMaterial({ color: '#4fbf7a' })); s.position.y = 16; g.add(s);
      dyn.dust[id] = s;
    });
  }
  // Slope radar sectors on the north wall.
  dyn.sectors = {};
  for (const sec of S.byId['sr-01']?.sectors || []) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(220, 120), new THREE.MeshBasicMaterial({ color: '#4fbf7a', transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false }));
    const p = P(...sec.geo);
    m.position.copy(p).add(new THREE.Vector3(0, 20, 0));
    m.lookAt(new THREE.Vector3(0, p.y, 0));
    m.userData.twin = 'sr-01';
    scene.add(m); pickables.push(m);
    dyn.sectors[sec.id] = m;
    addTag('sec-' + sec.id, `Сектор ${sec.id}`, () => m.position.clone().add(new THREE.Vector3(0, 80, 0)), { twin: 'sr-01', cls: 'small', prio: 3 });
  }
  // Effects: plume, blast ring, gas cloud, rain, truck dust.
  const puff = softSprite('rgba(255,255,255,1)', 'rgba(255,255,255,0)');
  dyn.plume = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), new THREE.MeshBasicMaterial({ color: '#b7a58a', transparent: true, opacity: 0.35, depthWrite: false }));
  dyn.plume.visible = false; scene.add(dyn.plume);
  dyn.exclusion = new THREE.Mesh(new THREE.RingGeometry(440, 450, 128), new THREE.MeshBasicMaterial({ color: '#e5534b', side: THREE.DoubleSide, transparent: true, opacity: 0.9 }));
  dyn.exclusion.rotation.x = -Math.PI / 2; dyn.exclusion.visible = false; scene.add(dyn.exclusion);
  dyn.gas = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 14), new THREE.MeshBasicMaterial({ color: '#d0b060', transparent: true, opacity: 0.28, depthWrite: false }));
  dyn.gas.visible = false; scene.add(dyn.gas);
  const rp = new Float32Array(5000 * 3);
  for (let i = 0; i < 5000; i++) { rp[i * 3] = -2500 + Math.random() * 8000; rp[i * 3 + 1] = Math.random() * 900 - 250; rp[i * 3 + 2] = -2500 + Math.random() * 5000; }
  const rg = new THREE.BufferGeometry(); rg.setAttribute('position', new THREE.BufferAttribute(rp, 3));
  dyn.rain = new THREE.Points(rg, new THREE.PointsMaterial({ color: '#cfe3f5', size: 5, transparent: true, opacity: 0.65, depthWrite: false }));
  dyn.rain.visible = false; scene.add(dyn.rain);
  dyn.bursts = [];
  dyn.puffMat = new THREE.SpriteMaterial({ map: puff, color: '#c8b48e', transparent: true, opacity: 0.0, depthWrite: false });
  dyn.puffs = [];
  for (let i = 0; i < 140; i++) { const s = new THREE.Sprite(dyn.puffMat.clone()); s.visible = false; scene.add(s); dyn.puffs.push({ s, life: 0 }); }
  dyn.puffNext = 0;
  // Selection marker: a glowing ring with a soft halo under the selected twin
  // (cyan in the diorama, copper in the realistic view).
  const selColor = DIORAMA ? '#45f0d8' : '#f0a56c';
  dyn.sel = new THREE.Group();
  const selRing = new THREE.Mesh(new THREE.RingGeometry(0.9, 1, 96), new THREE.MeshBasicMaterial({ color: selColor, transparent: true, opacity: 0.95, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
  const selHalo = new THREE.Mesh(new THREE.RingGeometry(0.55, 1.18, 96), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    uniforms: { color: { value: new THREE.Color(selColor) }, opacity: { value: 0.55 } },
    vertexShader: 'varying vec2 vP; void main(){ vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: 'uniform vec3 color; uniform float opacity; varying vec2 vP; void main(){ float r = length(vP); float a = exp(-pow((r - 0.95) / 0.09, 2.0)) + 0.18 * smoothstep(0.55, 0.95, r) * (1.0 - smoothstep(0.95, 1.18, r)); gl_FragColor = vec4(color, a * opacity); }',
  }));
  const selInner = new THREE.Mesh(new THREE.RingGeometry(0.62, 0.66, 64, 1, 0, Math.PI * 1.4), new THREE.MeshBasicMaterial({ color: selColor, transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
  for (const m of [selHalo, selRing, selInner]) { m.rotation.x = -Math.PI / 2; m.renderOrder = 4; dyn.sel.add(m); }
  dyn.selInner = selInner;
  dyn.sel.visible = false; scene.add(dyn.sel);
}

// ---------------------------------------------------------------- dynamic objects
const SCALE = DIORAMA
  ? { 'haul-truck': 2.1, 'water-truck': 2.1, loader: 2.1, drill: 2.1, 'light-vehicle': 3.0, personnel: 4.0 }
  : { 'haul-truck': 1.6, 'water-truck': 1.6, loader: 1.6, drill: 1.6, 'light-vehicle': 2.4, personnel: 3.2 };
const CAT_YELLOW = '#f2b329';
const TAGK = DIORAMA ? 1.35 : 1;   // label height above the (larger) diorama machines
function ensureDynamic(name, kind) {
  if (objs[name]) return objs[name];
  let o;
  const type = S.byId[name]?.type || '';
  if (kind === 'haul-truck') o = MD.haulTruck(DIORAMA ? CAT_YELLOW : '#d4824a', { small: /777/.test(type) });
  else if (kind === 'water-truck') o = MD.haulTruck('#4f8fbf', { water: true, small: true });
  else if (kind === 'loader') o = MD.shovel(name.startsWith('sh') || name.startsWith('ex'));
  else if (kind === 'drill') o = MD.drillRig();
  else if (kind === 'light-vehicle') o = MD.lightVehicle();
  else if (kind === 'personnel') o = MD.person();
  else if (kind === 'block') {
    o = new THREE.Group();
    const pad = new THREE.Mesh(new THREE.BoxGeometry(100, 1.5, 60), new THREE.MeshStandardMaterial({ color: '#56606b', transparent: true, opacity: 0.82, roughness: 0.9 }));
    pad.receiveShadow = true;
    // The block is a volume of rock one bench high: its sides go down to the
    // bench below, so the pad never hangs over the bench edge.
    const rockH = (S.site.layout.pit?.bench_h || 15) * VZ;
    const rock = new THREE.Mesh(new THREE.BoxGeometry(100, rockH, 60), new THREE.MeshStandardMaterial({ color: DIORAMA ? '#9a8466' : '#7c6c58', roughness: 0.95 }));
    rock.position.y = -rockH / 2 - 0.8;
    rock.receiveShadow = true;
    o.add(rock);
    o.add(pad);
    const holes = new THREE.InstancedMesh(new THREE.CylinderGeometry(1.1, 1.1, 2.2, 8), new THREE.MeshBasicMaterial({ color: '#ffffff' }), 160);
    holes.count = 0; holes.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(160 * 3), 3);
    o.add(holes);
    o.userData.parts = { pad, holes };
  } else return null;
  if (SCALE[kind]) o.scale.setScalar(SCALE[kind]);
  if (name.startsWith('ex')) o.scale.multiplyScalar(0.62);   // Hitachi EX870: ~82 t against 362 t of the EX3600
  if (env && !env.high) {
    MD.toLambert(o);
    if (o.userData.parts?.bodyMat) o.userData.parts.bodyMat = MD.lambertOf(o.userData.parts.bodyMat);
  }
  o.userData.twin = name;
  o.userData.kind = kind;
  scene.add(o); pickables.push(o);
  objs[name] = o;
  return o;
}

// Smooth motion: positions arrive every ~2 s; each moving twin keeps the last
// few samples and is drawn on the straight line between them, one polling
// interval in the past (snapshot interpolation), so it glides at a steady
// speed instead of lurching from one sample to the next.
const MOVERS = new Set(['haul-truck', 'water-truck', 'light-vehicle', 'personnel', 'drill', 'loader']);
let pollGap = POLL_MS;
function sampleAt(o, now) {
  const sm = o.userData.samples;
  const rt = now - pollGap * 1.15;
  if (rt <= sm[0].t) return sm[0];
  for (let i = sm.length - 1; i > 0; i--) {
    const a = sm[i - 1], b = sm[i];
    if (rt >= a.t) {
      if (rt >= b.t) return b;
      const f = (rt - a.t) / (b.t - a.t);
      return { p: a.p.clone().lerp(b.p, f), h: null, moving: a.p.distanceToSquared(b.p) > 0.25 };
    }
  }
  return sm[sm.length - 1];
}
function updateDynamic(dt) {
  const k = 1 - Math.exp(-dt / 0.7);
  const now = performance.now();
  const wsIdx = {};
  let wsN = 0;
  for (const it of S.catalog) {
    const kind = it.kind;
    if (!['haul-truck', 'water-truck', 'loader', 'drill', 'light-vehicle', 'personnel', 'block'].includes(kind)) continue;
    const t = S.t[it.id];
    if (!t || t.x === undefined) continue;
    const o = ensureDynamic(it.id, kind);
    if (!o) continue;
    let x = t.x, y = t.y, z = t.z;
    if (kind === 'haul-truck' && (t.state === 'in_workshop' || t.state === 'parked')) {
      // Spread the trucks inside the workshop / park line so they do not overlap.
      wsIdx[it.id] = wsN++;
      const i = wsIdx[it.id];
      x += -90 + (i % 6) * 42; y += 80 + Math.floor(i / 6) * 46;
    }
    const target = P(x, y, z);
    if (kind === 'haul-truck' || kind === 'water-truck' || kind === 'light-vehicle') {
      // Right-hand traffic: offset to the lane on the right of the heading.
      const h = (t.heading || 0) * Math.PI / 180;
      const lane = (kind === 'light-vehicle' ? 7 : 6) * (DIORAMA ? 1.4 : 1);
      target.x += Math.sin(h) * lane; target.z += Math.cos(h) * lane;
    }
    let travelYaw = null;
    if (MOVERS.has(kind)) {
      const sm = (o.userData.samples = o.userData.samples || []);
      const lastS = sm[sm.length - 1];
      if (!lastS || lastS.p.distanceToSquared(target) > 0.01 || lastS.src !== t) {
        if (lastS && lastS.p.distanceTo(target) > 2500) sm.length = 0;   // teleport (workshop, reset)
        if (!lastS || lastS.src !== t) { sm.push({ t: now, p: target.clone(), src: t }); if (sm.length > 4) sm.shift(); }
      }
      const cur = sampleAt(o, now);
      const prev = o.position.clone();
      if (!o.userData.init) { o.position.copy(cur.p); o.userData.init = true; }
      else o.position.copy(cur.p);
      const mv = o.position.clone().sub(prev);
      // Turn the body along the motion only while driving: a queued or parked
      // truck that is nudged up the line keeps its heading instead of spinning.
      if (cur.moving && mv.lengthSq() > 1e-4 && kind !== 'loader' && (kind !== 'haul-truck' || DRIVING.has(t.state))) travelYaw = Math.atan2(-mv.z, mv.x);
    } else if (!o.userData.init) { o.position.copy(target); o.userData.init = true; }
    else if (o.position.distanceTo(target) > 800) o.position.copy(target);
    else o.position.lerp(target, k);
    if (kind === 'block') {
      o.position.y += 1;
      o.rotation.y = (t.heading_deg || 0) * Math.PI / 180;
      const pad = o.userData.parts.pad;
      pad.material.color.set(BLOCK_COLORS[t.state] || '#56606b');
      const frac = t.state === 'mining' ? Math.max(0.12, (t.remaining || 0) / (t.tonnes_total || 1)) : 1;
      pad.scale.set(frac, 1, 1); pad.position.x = 50 * (1 - frac);
      o.visible = t.state !== 'depleted';
      const holes = o.userData.parts.holes;
      const n = Math.min(160, t.holes_total || 0), nd = Math.min(n, t.holes_drilled || 0), nc = Math.min(n, t.holes_charged || 0);
      const show = ['drilling', 'drilled', 'charging', 'charged'].includes(t.state);
      holes.count = show ? nd : 0;
      if (show && holes.userData.n !== n + nd * 1000 + nc * 1e6) {
        holes.userData.n = n + nd * 1000 + nc * 1e6;
        const cols = Math.max(4, Math.round(Math.sqrt(n * 1.6))), rows = Math.ceil(n / cols);
        const m4 = new THREE.Matrix4(), c = new THREE.Color();
        for (let i = 0; i < nd; i++) {
          const r = Math.floor(i / cols), cc = i % cols;
          m4.makeTranslation(-45 + (cc + 0.5) * (90 / cols), 1.5, -27 + (r + 0.5) * (54 / rows));
          holes.setMatrixAt(i, m4);
          c.set(i < nc ? '#ff7a2f' : '#e8eef3'); holes.setColorAt(i, c);
        }
        holes.instanceMatrix.needsUpdate = true; holes.instanceColor.needsUpdate = true;
      }
      if (S.prevBlockState[it.id] && S.prevBlockState[it.id] !== 'blasted' && t.state === 'blasted') blastFx(o.position.clone());
      S.prevBlockState[it.id] = t.state;
      continue;
    }
    if (t.heading !== undefined && kind !== 'loader') {
      // Face the direction of travel while moving; the reported heading otherwise.
      const target = travelYaw ?? (t.heading || 0) * Math.PI / 180;
      let d = target - o.rotation.y; d = Math.atan2(Math.sin(d), Math.cos(d));
      o.rotation.y += d * (1 - Math.exp(-dt / 0.35));
    }
    if (kind === 'haul-truck' || kind === 'water-truck') {
      const pr = o.userData.parts;
      const c = TRUCK_COLORS[t.state] || '#888';
      pr.ring.material.color.set(c);
      if (kind === 'haul-truck') {
        if (!DIORAMA) pr.bodyMat.color.set(c);
        else pr.bodyMat.color.set(['breakdown', 'towing'].includes(t.state) ? '#d9573f' : CAT_YELLOW);
        pr.load.visible = (t.payload || 0) > 1;
        const mat0 = t.material || '';
        pr.load.material.color.set(mat0.includes('вскрыш') ? '#8d8a85' : mat0.includes('глин') ? '#c8b58c' : '#8a5a34');
        const tilt = t.state === 'dumping' ? 0.75 : 0;
        pr.bed.rotation.z += (tilt - pr.bed.rotation.z) * Math.min(1, dt * 2);
      }
      // Dust from dry haul roads behind moving trucks.
      if ((t.speed || 0) > 12 && $('#lyrDust').checked && v(t.road || '', 'moisture', 20) < 45 && v('wx-01', 'rain', 0) < 0.2) emitPuff(o, t.speed);
    }
    if (kind === 'loader') {
      const pr = o.userData.parts, house = pr.house;
      const ph = performance.now() / 900;
      const want = (t.heading || 0) * Math.PI / 180 + (t.state === 'loading' ? Math.sin(ph) * 0.9 : 0);
      let d = want - house.rotation.y; d = Math.atan2(Math.sin(d), Math.cos(d));
      house.rotation.y += d * Math.min(1, dt * 2.5);
      if (pr.stick) {
        const dig = t.state === 'loading' ? Math.cos(ph) : 0;
        pr.stick.rotation.z = -1.5 + 0.35 * dig;
        pr.bucket.rotation.z = 0.9 - 0.5 * dig;
      }
    }
    if (kind === 'drill') {
      const m = o.userData.parts.mast;
      m.rotation.z += ((t.state === 'moving' ? 1.35 : 0) - m.rotation.z) * Math.min(1, dt * 1.5);
    }
    if (kind === 'personnel') o.userData.parts.ring.visible = !!t.alert;
  }
}

const puffTmp = new THREE.Vector3();
function emitPuff(o, speed) {
  if (Math.random() > 0.35) return;
  const p = dyn.puffs[dyn.puffNext]; dyn.puffNext = (dyn.puffNext + 1) % dyn.puffs.length;
  puffTmp.set(-14, 3, (Math.random() - 0.5) * 8).applyMatrix4(o.matrixWorld);
  p.s.position.copy(puffTmp);
  p.life = 0; p.max = 2.2 + Math.random() * 1.5; p.size = 14 + speed * 0.5; p.s.visible = true;
}
function updatePuffs(dt) {
  for (const p of dyn.puffs) {
    if (!p.s.visible) continue;
    p.life += dt;
    const f = p.life / p.max;
    if (f >= 1) { p.s.visible = false; continue; }
    p.s.scale.setScalar(p.size * (1 + f * 2.2));
    p.s.position.y += dt * 6;
    p.s.material.opacity = 0.38 * (1 - f) * Math.min(1, p.life * 4);
  }
}

function blastFx(pos) {
  const n = 400, p = new Float32Array(n * 3), vel = [];
  for (let i = 0; i < n; i++) { p[i * 3] = pos.x; p[i * 3 + 1] = pos.y; p[i * 3 + 2] = pos.z; vel.push(new THREE.Vector3((Math.random() - 0.5) * 160, 60 + Math.random() * 220, (Math.random() - 0.5) * 160)); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  const pts = new THREE.Points(g, new THREE.PointsMaterial({ color: '#ffb35c', size: 14, transparent: true, opacity: 1 }));
  scene.add(pts);
  const flash = new THREE.PointLight('#ffb35c', 2e6, 3000, 2); flash.position.copy(pos).add(new THREE.Vector3(0, 80, 0)); scene.add(flash);
  const cloud = [];
  for (let i = 0; i < 26; i++) {
    const s = new THREE.Sprite(dyn.puffMat.clone());
    s.material.color.set(i % 3 ? '#a8957a' : '#8c7a64');
    s.position.copy(pos).add(new THREE.Vector3((Math.random() - 0.5) * 120, 10 + Math.random() * 40, (Math.random() - 0.5) * 80));
    s.userData.v = new THREE.Vector3((Math.random() - 0.5) * 30, 25 + Math.random() * 35, (Math.random() - 0.5) * 30);
    scene.add(s); cloud.push(s);
  }
  dyn.bursts.push({ pts, vel, t: 0, flash, cloud });
  showBanner('ВЗРЫВ: массовый взрыв на блоке — ожидание проветривания', 'alarm', 8000);
}

function updateEffects(dt, time) {
  // Conveyor parcels.
  const load = v('cv-01', 'load_tph', 0);
  const n = Math.min(70, Math.round(load / 5200 * 70));
  dyn.parcels.count = n;
  const m4 = new THREE.Matrix4();
  for (let i = 0; i < n; i++) {
    const f = ((i / 70) + time * 0.012) % 1;
    const p = dyn.convA.clone().lerp(dyn.convB, f);
    m4.makeTranslation(p.x, p.y, p.z);
    dyn.parcels.setMatrixAt(i, m4);
  }
  dyn.parcels.instanceMatrix.needsUpdate = true;
  const pk = v('gc-01', 'pocket_t', 0);
  dyn.pocket.scale.y = Math.max(0.5, pk / 700 * 16); dyn.pocket.position.y = 42 + dyn.pocket.scale.y / 2;
  if (dyn.radarDish) dyn.radarDish.rotation.y = Math.sin(time * 0.3) * 0.9;
  if (dyn.pqLamp) dyn.pqLamp.material.color.set(v('pq-01', 'violations', 'нет') !== 'нет' ? '#e5534b' : '#4fbf7a');
  if (dyn.seisLamp) dyn.seisLamp.material.color.set(v('sm-01', 'alarm_ml') ? '#e5534b' : '#4fbf7a');
  if (dyn.enBar) { const h = Math.max(1, (v('en-01', 'p_mw', 0) - 120) * 0.35); dyn.enBar.scale.y += (h - dyn.enBar.scale.y) * 0.05; dyn.enBar.position.y = dyn.enBar.scale.y / 2; }
  if (dyn.mwdScreen) dyn.mwdScreen.material.emissive.set(v('mwd-01', 'ml_match', true) ? '#3fd08a' : '#f2b13a');
  if (dyn.qcScreen) dyn.qcScreen.material.emissive.set(v('qc-01', 'silica_ml', 0) > 3.5 ? '#ff7a3f' : '#3fb8ff');
  updatePuffs(dt);
  const cos = v('cos-01', 'level_kt', 18);
  const s = Math.sqrt(Math.max(cos, 0.5) / 45);
  dyn.cos.scale.set(30 + 70 * s, 10 + 30 * s, 30 + 70 * s); dyn.cos.position.y = dyn.cos.scale.y / 2;
  const lg = v('lg-01', 'stock_kt', 400);
  const sl = Math.sqrt(Math.max(lg, 1) / 400);
  dyn.lg.scale.set(140 * sl, 26 * sl, 140 * sl); dyn.lg.position.y = 13 * sl;
  dyn.sag.rotation.x += dt * (v('sag-01', 'power_mw', 0) / 25) * 1.4;
  for (const b of dyn.bm) b.rotation.x += dt * (v('bm-01', 'power_mw', 0) / 13) * 1.8;
  dyn.scrubber.rotation.x += dt * (v('cp-01', 'throughput', 0) / 620) * 1.5;
  for (const r of dyn.rakes || []) r.rotation.y += dt * 0.15;
  const rec = v('fl-r', 'recovery', 76);
  const froth = new THREE.Color('#6d7f3a').lerp(new THREE.Color('#d6b34a'), Math.min(1, Math.max(0, (rec - 60) / 25)));
  for (const f of dyn.froth) f.material.color.copy(froth);
  const ntu = v('th-t', 'overflow_ntu', 30);
  dyn.tailsWater?.material.color.set(ntu > 60 ? '#9c8a62' : '#7d8c86');
  dyn.subGlow.material.color.set(v('energy', 'tariff_zone') === 'пик' ? '#e5534b' : '#5aa6e8');
  dyn.subGlow.scale.setScalar(0.8 + v('ss-220', 'total_mw', 60) / 80 + 0.15 * Math.sin(time * 3));
  dyn.windArrow.rotation.y = ((v('wx-01', 'wind_dir', 240) + 180) % 360 - 90) * -Math.PI / 180;
  const dustOn = $('#lyrDust').checked;
  for (const [id, s1] of Object.entries(dyn.dust)) {
    const pm = v(id, 'pm10', 20);
    s1.material.color.set(pm > 150 ? '#e5534b' : pm > 80 ? '#e6b13a' : '#4fbf7a');
    s1.scale.setScalar(1 + Math.min(4, pm / 80));
  }
  for (const [sid, m] of Object.entries(dyn.sectors)) {
    const lvl = v('sr-01', `${sid.toLowerCase()}_level`, 'green');
    m.material.color.set(LEVEL_COLORS[lvl] || '#4fbf7a');
    m.material.opacity = lvl === 'green' ? 0.25 : 0.45 + 0.2 * Math.sin(time * 4);
    const tg = tags['sec-' + sid];
    if (tg) tg.el.innerHTML = `${sid}: <b>${num(v('sr-01', `${sid.toLowerCase()}_velocity`), 1)}</b> мм/сут`;
    if (tg) tg.el.className = 'tag small' + (lvl === 'red' ? ' alarm' : lvl === 'amber' ? ' warn' : '');
  }
  const plumeOn = v('safety', 'plume_active', false) && dustOn;
  dyn.plume.visible = !!plumeOn;
  if (plumeOn) {
    const r = v('safety', 'plume_r', 60);
    dyn.plume.position.copy(P(v('safety', 'plume_x', 0), v('safety', 'plume_y', 0), 40));
    dyn.plume.scale.set(r, r * 0.45, r);
    dyn.plume.material.opacity = Math.min(0.55, 0.12 + v('safety', 'plume_mass', 0) / 120000);
  }
  const bs = v('drill-blast', 'blast_state', 'нет');
  const charged = S.catalog.filter((c) => c.kind === 'block').map((c) => S.t[c.id]).find((t) => t && t.state === 'charged');
  dyn.exclusion.visible = bs === 'эвакуация' && !!charged;
  if (dyn.exclusion.visible) { dyn.exclusion.position.copy(P(charged.x, charged.y, charged.z)); dyn.exclusion.position.y += 3; dyn.exclusion.material.opacity = 0.5 + 0.4 * Math.sin(time * 5); }
  const co = v('gm-01', 'co', 0);
  dyn.gas.visible = dustOn && co > 5;
  if (dyn.gas.visible) { dyn.gas.position.copy(P(v('gm-01', 'x', 0), v('gm-01', 'y', 0), v('gm-01', 'z', 0))); dyn.gas.scale.setScalar(60 + co * 0.8); }
  const rain = v('wx-01', 'rain', 0);
  dyn.rain.visible = rain > 0.1;
  if (dyn.rain.visible) {
    const a = dyn.rain.geometry.attributes.position;
    for (let i = 0; i < a.count; i++) { let y = a.getY(i) - dt * 700; if (y < -260) y += 1150; a.setY(i, y); }
    a.needsUpdate = true;
    dyn.rain.material.opacity = Math.min(0.85, 0.25 + rain / 8);
  }
  for (const b of [...dyn.bursts]) {
    b.t += dt;
    const a = b.pts.geometry.attributes.position;
    for (let i = 0; i < b.vel.length; i++) { b.vel[i].y -= 160 * dt; a.setXYZ(i, a.getX(i) + b.vel[i].x * dt, Math.max(a.getY(i) + b.vel[i].y * dt, -260), a.getZ(i) + b.vel[i].z * dt); }
    a.needsUpdate = true;
    b.pts.material.opacity = Math.max(0, 1 - b.t / 4);
    b.flash.intensity = Math.max(0, 2e6 * (1 - b.t * 1.2));
    for (const c of b.cloud) {
      c.position.addScaledVector(c.userData.v, dt); c.userData.v.multiplyScalar(1 - dt * 0.25);
      c.scale.setScalar(60 + b.t * 70);
      c.material.opacity = Math.max(0, 0.55 * Math.min(1, b.t * 3) * (1 - b.t / 9));
    }
    if (b.t > 9) { scene.remove(b.pts); scene.remove(b.flash); for (const c of b.cloud) scene.remove(c); dyn.bursts.splice(dyn.bursts.indexOf(b), 1); }
  }
  // Roads
  for (const [rid, m] of Object.entries(roadMats)) {
    const st = v(rid, 'status_code', 'open');
    const moist = v(rid, 'moisture', 30) / 100;
    const c = new THREE.Color(ROAD_COLORS[st] || ROAD_COLORS.open);
    if (st === 'open') c.lerp(new THREE.Color('#3f3a33'), moist * 0.6);
    m.color.copy(c);
  }
}

// ---------------------------------------------------------------- labels
const tmpV = new THREE.Vector3();
// Labels are placed by priority (alarms, the selected twin, loaders, plant)
// and a label that would overlap one already placed is hidden: the scene
// stays readable from the overview down to a single machine.
let tagFrame = 0;
const setDisp = (t, on) => { if (t.vis !== on) { t.el.style.display = on ? '' : 'none'; t.vis = on; } };
function updateTags() {
  if ((tagFrame++ & 1) && !tween) return;           // every other frame is enough
  const r = canvas.getBoundingClientRect();
  const cand = [];
  for (const t of Object.values(tags)) {
    if (!t.show()) { setDisp(t, false); continue; }
    const p = t.pos();
    if (!p) { setDisp(t, false); continue; }
    tmpV.copy(p).project(camera);
    if (tmpV.z > 1 || Math.abs(tmpV.x) > 1.05 || Math.abs(tmpV.y) > 1.05) { setDisp(t, false); continue; }
    const pr = t.prio + (t.el.classList.contains('alarm') ? 10 : 0) + (t.twin && t.twin === S.selected ? 20 : 0);
    cand.push({ t, x: (tmpV.x + 1) / 2 * r.width, y: (1 - tmpV.y) / 2 * r.height, pr, z: tmpV.z });
  }
  cand.sort((a, b) => b.pr - a.pr || a.z - b.z);
  const placed = [];
  for (const c of cand) {
    const t = c.t;
    if (!t.w) { setDisp(t, true); t.w = t.el.offsetWidth || 60; t.h = t.el.offsetHeight || 16; }
    const box1 = { l: c.x - t.w / 2 - 2, r: c.x + t.w / 2 + 2, t: c.y - t.h * 1.2 - 2, b: c.y + 2 };
    const hit = placed.some((p) => !(box1.r < p.l || box1.l > p.r || box1.b < p.t || box1.t > p.b));
    if (hit && c.pr < 20) { setDisp(t, false); continue; }
    placed.push(box1);
    setDisp(t, true);
    t.el.style.transform = `translate(${c.x - t.w / 2}px, ${c.y - t.h * 1.2}px)`;
  }
}
function dynamicTags() {
  for (const it of S.catalog) {
    if (tags['dyn-' + it.id]) continue;
    if (it.kind === 'loader') {
      addTag('dyn-' + it.id, '', () => objs[it.id] && objs[it.id].position.clone().add(new THREE.Vector3(0, 60 * TAGK, 0)), { twin: it.id, prio: 4 });
    } else if (it.kind === 'drill') {
      addTag('dyn-' + it.id, '', () => objs[it.id] && objs[it.id].position.clone().add(new THREE.Vector3(0, 70 * TAGK, 0)), { twin: it.id, cls: 'small', prio: 3 });
    } else if (it.kind === 'haul-truck') {
      addTag('dyn-' + it.id, '', () => objs[it.id] && objs[it.id].position.clone().add(new THREE.Vector3(0, 34 * TAGK, 0)), {
        twin: it.id, cls: 'small',
        show: () => $('#lyrTruckLabels').checked || S.selected === it.id || ['breakdown', 'towing'].includes(v(it.id, 'state')),
      });
    } else if (it.kind === 'personnel') {
      addTag('dyn-' + it.id, '', () => objs[it.id] && objs[it.id].position.clone().add(new THREE.Vector3(0, 26 * TAGK, 0)), {
        twin: it.id, cls: 'small alarm', show: () => !!v(it.id, 'alert') || S.selected === it.id,
      });
    } else if (it.kind === 'block') {
      addTag('dyn-' + it.id, '', () => objs[it.id] && objs[it.id].visible && objs[it.id].position.clone().add(new THREE.Vector3(0, 18 * TAGK, 0)), {
        twin: it.id, cls: 'small', show: () => $('#lyrLabels').checked && orbit.dist < 3600 * LENS,
      });
    }
  }
}
function refreshTagText() {
  for (const it of S.catalog) {
    const t = tags['dyn-' + it.id];
    if (!t) continue;
    t.w = 0;
    const s = S.t[it.id] || {};
    if (it.kind === 'loader') {
      const bad = ['breakdown', 'down', 'starved', 'slope_hold'].includes(s.state);
      t.el.className = 'tag' + (bad ? ' alarm' : s.state === 'blast_standby' ? ' warn' : '');
      t.el.innerHTML = `<b>${it.id.toUpperCase()}</b> ${esc(s.state_ru || '')} · ${num(s.block_grade, 2)}% · очередь ${num(s.queue)}`;
    } else if (it.kind === 'drill') {
      t.el.innerHTML = `<b>${it.id.toUpperCase()}</b> ${esc(s.state_ru || '')} ${s.state === 'drilling' ? num(s.rop, 0) + ' м/ч' : ''}`;
    } else if (it.kind === 'haul-truck') {
      t.el.className = 'tag small' + (['breakdown', 'towing'].includes(s.state) ? ' alarm' : '');
      t.el.innerHTML = `<b>${it.id.toUpperCase()}</b> ${num(s.payload, 0)} т · ${num(s.speed, 0)} км/ч${s.cm_codes_count ? ` · ⚠ ${esc(String(s.cm_codes || '').split(':')[0])}` : ''}`;
      if (s.cm_codes_count && !t.el.className.includes('alarm')) t.el.className = 'tag small warn';
    } else if (it.kind === 'personnel') {
      t.el.innerHTML = `⚠ ${it.id.toUpperCase()}: самосвал в ${num(s.nearest_truck_m, 0)} м`;
    } else if (it.kind === 'block') {
      t.el.innerHTML = `${esc(s.code || '')} · ${esc(s.state_ru || '')}`;
    }
  }
}

// ---------------------------------------------------------------- panels
const KPI_DEF = [
  ['concentrator', 'throughput', 'ЗИФ, т/ч', 0, 'sag-01'],
  ['site', 'feed_grade', 'Cu в питании, %', 3, 'geology'],
  ['site', 'recovery', 'Извлечение, %', 1, 'fl-r'],
  ['site', 'cu_tph', 'Медь, т/ч', 2, 'fl-c'],
  ['site', 'cu_plan_pct', 'План меди, %', 0, 'site'],
  ['site', 'power_mw', 'Нагрузка, МВт', 1, 'ss-220'],
  ['site', 'diesel_lph', 'ДТ, л/ч', 0, 'fs-01'],
  ['site', 'fleet_availability', 'КТГ, %', 1, 'maintenance'],
  ['site', 'alarms_active', 'Тревоги', 0, 'safety'],
];
function renderKpis() {
  const box1 = $('#kpis');
  if (!box1.children.length) {
    for (const [, , l, , twin] of KPI_DEF) {
      const d = el('div', 'kpi', `<div class="v">—</div><div class="l">${l}</div>`);
      d.addEventListener('click', () => select(twin));
      box1.appendChild(d);
    }
  }
  KPI_DEF.forEach(([tw, f, , n], i) => {
    const d = box1.children[i];
    const val = v(tw, f);
    d.querySelector('.v').textContent = num(val, n);
    d.classList.toggle('bad', (f === 'alarms_active' && val > 0) || (f === 'cu_plan_pct' && val < 85));
    d.classList.toggle('warn', f === 'cu_plan_pct' && val >= 85 && val < 97);
  });
  $('#simTime').textContent = v('site', 'sim_time', '—');
  $('#shift').textContent = `смена: ${v('site', 'shift', '—')}`;
  const sp = v('site', 'sim_speed', 10);
  document.querySelectorAll('.speed button').forEach((b) => b.classList.toggle('active', +b.dataset.speed === +sp));
}

function renderEvents() {
  let evs = [];
  try { evs = JSON.parse(v('site', 'events', '[]')); } catch (e) { /* ignore */ }
  const box1 = $('#events');
  box1.innerHTML = '';
  for (const e of evs) {
    const d = el('div', 'ev ' + e.lvl, `<div class="t">${esc(e.t)} · ${esc(e.twin || '')}</div>${esc(e.msg)}`);
    if (e.twin && S.byId[e.twin]) d.addEventListener('click', () => select(e.twin));
    box1.appendChild(d);
  }
  const top = evs.find((e) => e.lvl === 'alarm');
  if (top && top.t !== S.lastAlarm) { S.lastAlarm = top.t + top.msg; if (S.firstData) showBanner(top.msg, 'alarm', 7000); }
}
let bannerTimer = null;
function showBanner(text, cls, ms) {
  const b = $('#banner');
  b.textContent = text; b.className = 'banner ' + (cls === 'warn' ? 'warn' : '');
  clearTimeout(bannerTimer); bannerTimer = setTimeout(() => b.classList.add('hidden'), ms);
}

// Scenarios ----------------------------------------------------------------
const MANUAL = [
  ['trucks_parked', 'Самосвалов в резерве', 'number', { min: 0, max: 10, step: 1 }],
  ['loader_down', 'Остановить экскаватор', 'select', { options: [['none', 'нет'], ['sh-01', 'SH-01 (руда)'], ['sh-02', 'SH-02 (богатая)'], ['sh-03', 'SH-03 (вскрыша)'], ['ld-01', 'LD-01 (глина)'], ['sh-04', 'SH-04 (Восточный, руда)'], ['ex-01', 'EX-01 (Восточный, вскрыша)']] }],
  ['east_ore_share', 'Доля руды с Восточного карьера', 'number', { min: 0, max: 1, step: 0.05 }],
  ['trucks_east', 'CAT 785C на Восточном карьере', 'number', { min: 0, max: 12, step: 1 }],
  ['trucks_777_east', 'CAT 777D на вскрыше Восточного', 'number', { min: 0, max: 5, step: 1 }],
  ['waste_central_tph', 'Вскрыша Центрального (SH-03), т/ч', 'number', { min: 0, max: 3500, step: 100 }],
  ['waste_east_tph', 'Вскрыша Восточного (EX-01), т/ч', 'number', { min: 0, max: 1200, step: 100 }],
  ['crusher_down', 'Остановить ККД-1', 'checkbox'],
  ['powder_factor', 'Удельный расход ВВ, кг/м³', 'number', { min: 0.35, max: 1.2, step: 0.05 }],
  ['grade_target', 'Целевое Cu в питании, %', 'number', { min: 0.3, max: 0.5, step: 0.01 }],
  ['dispatch_policy', 'Диспетчеризация', 'select', { options: [['blend', 'по потребности и качеству'], ['min_queue', 'минимум очереди'], ['fixed', 'закрепление']] }],
  ['rain_mm_h', 'Дождь, мм/ч', 'number', { min: 0, max: 10, step: 0.5 }],
  ['road_closed', 'Закрыть дорогу', 'select', { options: [['none', 'нет'], ['road-crusher', 'на ККД'], ['road-bypass', 'объездная'], ['road-dump', 'на отвал'], ['road-clay', 'на глин. фабрику'], ['road-lg', 'на склад забаланса'], ['road-east', 'Восточный — ККД'], ['road-dump-east', 'на Восточный отвал']] }],
  ['speed_limit_kmh', 'Ограничение скорости, км/ч', 'number', { min: 20, max: 50, step: 5 }],
  ['peak_shaving', 'Снижение нагрузки в пик', 'checkbox'],
  ['harmonic_filter', 'ФКУ (фильтр гармоник) включена', 'checkbox'],
  ['maintenance_strategy', 'Стратегия ТОиР', 'select', { options: [['preventive', 'по наработке'], ['predictive', 'по состоянию (PdM)'], ['reactive', 'по отказу']] }],
];
function buildScenarioPanel() {
  const box1 = $('#presets');
  let group = null;
  for (const [key, p] of Object.entries(S.presets)) {
    if (p.group !== group) { group = p.group; box1.appendChild(el('div', 'preset-group', esc(group))); }
    const b = el('button', 'preset', `<div class="t">${esc(p.title)}</div><div class="w">${esc(p.why)}</div>`);
    b.dataset.key = key;
    b.addEventListener('click', () => applyPreset(key));
    box1.appendChild(b);
  }
  const f = $('#manual');
  for (const [k, l, type, o] of MANUAL) {
    f.appendChild(el('label', null, esc(l)));
    let inp;
    if (type === 'select') { inp = el('select'); for (const [val, txt] of o.options) { const op = el('option', null, esc(txt)); op.value = val; inp.appendChild(op); } }
    else { inp = el('input'); inp.type = type; if (o) Object.assign(inp, o); }
    inp.name = k;
    f.appendChild(inp);
  }
  const ap = el('button', 'btn primary', 'Применить параметры');
  ap.type = 'submit';
  f.appendChild(ap);
  f.addEventListener('submit', (e) => {
    e.preventDefault();
    const vals = { preset: 'manual' };
    for (const [k, , type] of MANUAL) {
      const inp = f.elements[k];
      vals[k] = type === 'checkbox' ? inp.checked : type === 'number' ? +inp.value : inp.value;
    }
    setControl(vals);
  });
  $('#blastNow').addEventListener('click', () => setControl({ blast_now: (v('control', 'blast_now', 0) || 0) + 1 }));
  document.querySelectorAll('.speed button').forEach((b) => b.addEventListener('click', () => setControl({ sim_speed: +b.dataset.speed })));
}
function applyPreset(key) {
  const p = S.presets[key];
  const vals = { ...S.defaults, ...p.set, preset: key };
  delete vals.sim_speed; delete vals.blast_now; delete vals.plan_optimize;
  setControl(vals);
}
function syncManualForm() {
  const f = $('#manual');
  if (f.contains(document.activeElement)) return;
  for (const [k, , type] of MANUAL) {
    const inp = f.elements[k];
    const val = v('control', k);
    if (inp && val !== undefined) { if (type === 'checkbox') inp.checked = !!val; else inp.value = val; }
  }
  const preset = v('control', 'preset', 'baseline');
  document.querySelectorAll('.preset').forEach((b) => b.classList.toggle('active', b.dataset.key === preset));
  $('#scenActive').textContent = (preset !== 'manual' && S.presets[preset]?.title) || v('whatif', 'scenario', preset);
}
const FC_ROWS = [
  ['margin_mkzt', 1, 1], ['cu_t', 0, 1], ['month_ore_kt', 0, 1], ['month_cu_t', 0, 1],
  ['exposed6_central_mo', 1, 1], ['exposed6_east_mo', 1, 1], ['ore_east_pct', 0, 0], ['feed_grade', 3, 1],
  ['strip_central', 2, 1], ['strip_east', 2, 1], ['ore_t', 0, 1], ['waste_t', 0, 1], ['mill_t', 0, 1],
  ['recovery', 1, 1], ['kwh_t', 1, -1], ['diesel_l', 0, -1], ['cost_kzt_t_cu', 0, -1], ['fleet_avail', 1, 1],
  ['failures', 0, -1], ['inband_pct', 0, 1], ['queue_min', 1, -1], ['cos_end_kt', 1, 1], ['co2_t', 0, -1], ['cas_alerts', 0, -1], ['pq_ok_pct', 0, 1],
];
// Monthly plan ------------------------------------------------------------------
// The decision of the Concept on one screen: the allocation sliders write the
// control twin, the 48 h forecast answers with the month and the six-month
// exposed-ore trajectory of both pits; «Подобрать план» asks the twin to play
// eight allocations and rank them.
const PLAN_FIELDS = {
  east_ore_share: (x) => `${num(x * 100)} %`, trucks_east: (x) => `${num(x)} шт`, trucks_777_east: (x) => `${num(x)} шт`,
  waste_central_tph: (x) => `${num(x)} т/ч`, waste_east_tph: (x) => `${num(x)} т/ч`,
};
function planValues() {
  const f = $('#planForm');
  const vals = {};
  for (const k of Object.keys(PLAN_FIELDS)) vals[k] = +f.elements[k].value;
  vals.maintenance_strategy = f.elements.pdm.checked ? 'predictive' : 'preventive';
  return vals;
}
function buildPlanPanel() {
  const f = $('#planForm');
  if (!f) return;
  for (const k of Object.keys(PLAN_FIELDS)) {
    f.elements[k].addEventListener('input', () => { f.dataset.dirty = '1'; $('#o_' + k).textContent = PLAN_FIELDS[k](+f.elements[k].value); });
  }
  f.elements.pdm.addEventListener('change', () => { f.dataset.dirty = '1'; });
  f.addEventListener('submit', (e) => {
    e.preventDefault();
    setControl({ ...planValues(), preset: 'plan' });
    delete f.dataset.dirty;
    showBanner('План отправлен в двойник: прогноз на 48 ч считается', '', 3500);
  });
  $('#planAuto').addEventListener('click', () => {
    setControl({ plan_optimize: (+v('control', 'plan_optimize', 0) || 0) + 1 });
    showBanner('Двойник проигрывает 8 расстановок по 48 ч — 1–3 минуты', '', 4000);
  });
}
function syncPlanForm() {
  const f = $('#planForm');
  // Values the user is still setting are not overwritten by the twin.
  if (!f || f.dataset.dirty || f.contains(document.activeElement)) return;
  for (const k of Object.keys(PLAN_FIELDS)) {
    const val = v('control', k);
    if (val !== undefined) { f.elements[k].value = val; $('#o_' + k).textContent = PLAN_FIELDS[k](+val); }
  }
  f.elements.pdm.checked = v('control', 'maintenance_strategy') === 'predictive';
}
function planChart(traj) {
  const svg = $('#planChart');
  if (!svg) return;
  const W = 300, H = 170, L = 26, R = 8, T = 10, B = 22;
  const all = [];
  for (const run of ['base', 'scen']) for (const p of ['central', 'east']) all.push(...(traj?.[run]?.[p] || []));
  const ymax = Math.max(3, Math.ceil(Math.max(...all, 0) + 0.5));
  const X = (m) => L + (W - L - R) * m / 6, Y = (y) => T + (H - T - B) * (1 - Math.min(y, ymax) / ymax);
  let h = '';
  for (let y = 0; y <= ymax; y += ymax > 6 ? 2 : 1) h += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(y)}" y2="${Y(y)}"/><text x="${L - 4}" y="${Y(y) + 3}" text-anchor="end">${y}</text>`;
  for (let m = 0; m <= 6; m++) h += `<text x="${X(m)}" y="${H - 8}" text-anchor="middle">${m}</text>`;
  h += `<text x="${W - R}" y="${H - 1}" text-anchor="end">месяцы</text><text x="2" y="${T - 2}">мес запаса</text>`;
  const lim = traj?.min_months ?? 1.5;
  h += `<line class="lim" x1="${L}" x2="${W - R}" y1="${Y(lim)}" y2="${Y(lim)}"/>`;
  const path = (arr) => arr.map((y, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(y).toFixed(1)}`).join(' ');
  for (const [run, cls] of [['base', ' base'], ['scen', '']]) {
    for (const p of ['central', 'east']) {
      const arr = traj?.[run]?.[p];
      if (arr?.length) h += `<path class="${p === 'central' ? 'c' : 'e'}${cls}" d="${path(arr)}"/>`;
    }
  }
  svg.innerHTML = h;
}
function renderPlan() {
  if (!$('#planTiles')) return;
  const st = v('whatif', 'status', '—');
  const isPlan = v('control', 'preset') === 'plan';
  $('#planStatus').textContent = st; $('#planStatus').className = 'pill ' + (st === 'готов' ? 'ok' : 'busy');
  $('#planMeta').textContent = `${isPlan ? 'план совещания' : v('whatif', 'scenario', '')} · от ${v('whatif', 'computed_at', '—')}`;
  const tile = (label, key, n, unit, dir, ref) => {
    const b = v('whatif', 'base_' + key), s1 = v('whatif', 'scen_' + key);
    if (s1 === undefined) return '';
    const d = s1 - b;
    const cls = ref !== undefined ? (s1 >= ref ? 'good' : 'bad') : (Math.abs(d) < 1e-6 || !dir ? '' : (d * dir > 0 ? 'good' : 'bad'));
    return `<div class="plan-tile ${cls}"><div class="l">${esc(label)}</div><div class="v">${num(s1, n)} <span class="muted small">${unit}</span></div><div class="d">текущий план ${num(b, n)}${ref !== undefined ? ` · нужно ${num(ref, n)}` : ''}</div></div>`;
  };
  $('#planTiles').innerHTML =
    tile('Руда фабрике за месяц', 'month_ore_kt', 0, 'кт', 1, 2740 * 0.97) +
    tile('Медь за месяц', 'month_cu_t', 0, 'т', 1) +
    tile('Медь за 6 мес с учётом запасов', 'cu_6m_kt', 1, 'кт', 1) +
    tile('Недобор руды за 6 мес', 'ore_short_6m_kt', 0, 'кт', -1) +
    tile('Вскрыто через 6 мес: Центральный', 'exposed6_central_mo', 1, 'мес', 1, 1.5) +
    tile('Вскрыто через 6 мес: Восточный', 'exposed6_east_mo', 1, 'мес', 1, 1.5);
  let traj = null;
  try { traj = JSON.parse(v('whatif', 'plan_traj', 'null')); } catch (e) { traj = null; }
  if (traj) planChart(traj);
  // auto-selection
  const ps = v('whatif', 'plan_status', 'нет');
  $('#optStatus').textContent = ps === 'нет' ? '—' : ps;
  $('#optStatus').className = 'pill ' + (ps === 'готов' ? 'ok' : ps === 'подбор' ? 'busy' : '');
  let opts = null;
  try { opts = JSON.parse(v('whatif', 'plan_options', 'null')); } catch (e) { opts = null; }
  const tb = $('#optTable tbody');
  const key = JSON.stringify(opts?.options?.map((o) => o.score)) + ps;
  if (tb.dataset.key === key) return;
  tb.dataset.key = key;
  tb.innerHTML = '';
  if (!opts?.options) return;
  const nOk = opts.options.filter((o) => o.feasible).length;
  $('#optMeta').textContent = `Подобрано ${v('whatif', 'plan_computed_at', '')} за ${num(v('whatif', 'plan_calc_s'), 0)} с. `
    + `Жёсткие условия: у каждого карьера через полгода ≥ ${num(opts.min_months, 1)} мес вскрытой руды, руды фабрике ≥ ${num(opts.ore_share * 100)} % плана. `
    + (opts.any_feasible === false
      ? `Ни один вариант их не выполняет — показан ближайший к условиям «${v('whatif', 'plan_best', '')}»: нужна другая расстановка или больше техники.`
      : `Выполняют ${nOk} из ${opts.options.length}; среди них лучший по меди за 6 мес с учётом запасов — «${v('whatif', 'plan_best', '')}».`);
  tb.appendChild(el('tr', null, '<th>Вариант</th><th>Cu 6 мес, кт</th><th>Ц, мес</th><th>В, мес</th><th>руда, кт</th><th>усл.</th><th></th>'));
  for (const o of [...opts.options].sort((a, b) => (b.feasible - a.feasible) || (b.score - a.score))) {
    const k = o.kpi, lo = (x) => (x < opts.min_months ? 'low' : '');
    const c = o.control;
    const tip = `доля Вост. ${num(c.east_ore_share * 100)} %, 785C на Вост. ${c.trucks_east}, 777D на вскрыше Вост. ${c.trucks_777_east}, вскрыша ${num(c.waste_central_tph)} / ${num(c.waste_east_tph)} т/ч`;
    const oreLow = k.month_ore_kt < opts.ore_share * 2740 ? 'low' : '';
    const tr = el('tr', o.best ? 'best' : '', `<td title="${esc(tip)}">${o.best ? '★ ' : ''}${esc(o.name)}</td><td>${num(k.cu_6m_kt, 1)}</td><td class="${lo(k.exposed6_central_mo)}">${num(k.exposed6_central_mo, 1)}</td><td class="${lo(k.exposed6_east_mo)}">${num(k.exposed6_east_mo, 1)}</td><td class="${oreLow}">${num(k.month_ore_kt, 0)}</td><td class="${o.feasible ? '' : 'low'}">${o.feasible ? '✓' : '✗'}</td><td><button type="button">Применить</button></td>`);
    tr.querySelector('button').addEventListener('click', () => {
      setControl({ ...o.control, preset: 'plan' });
      delete $('#planForm').dataset.dirty;
      showBanner(`Применён вариант «${o.name}»: прогноз считается`, '', 3500);
    });
    tb.appendChild(tr);
  }
}
function renderForecast() {
  const st = v('whatif', 'status', '—');
  const pill = $('#fcStatus');
  pill.textContent = st; pill.className = 'pill ' + (st === 'готов' ? 'ok' : 'busy');
  $('#fcMeta').textContent = `${v('whatif', 'scenario', '')} · от ${v('whatif', 'computed_at', '—')} (расчёт ${num(v('whatif', 'calc_s'), 1)} с)`;
  const labels = S.byId.whatif?.kpi_labels || {};
  const tb = $('#fcTable tbody');
  tb.innerHTML = '';
  const showAll = $('#fcAll')?.open;
  for (const [i, [k, n, dir]] of FC_ROWS.entries()) {
    if (i >= 8 && !showAll) break;
    const b = v('whatif', 'base_' + k), s1 = v('whatif', 'scen_' + k), d = v('whatif', 'delta_' + k, 0);
    if (b === undefined) continue;
    const good = Math.abs(d) < 0.5 || !dir ? '' : (d * dir > 0 ? 'good' : 'badv');
    const lab = labels[k] || { label: k, unit: '' };
    const w = Math.min(50, Math.abs(d) / 2);
    tb.appendChild(el('tr', null, `<td class="k">${esc(lab.label)}<div class="bar"><i style="left:${d < 0 ? 50 - w : 50}%;width:${w}%;background:${good === 'good' ? 'var(--ok)' : good ? 'var(--bad)' : '#556'}"></i></div></td>
      <td class="n">${cnum(b, n)} → ${cnum(s1, n)} <span class="muted small">${esc(lab.unit)}</span></td><td class="d ${good}">${d > 0 ? '+' : ''}${num(d, 1)}%</td>`));
  }
}

// Tree ------------------------------------------------------------------------
// In Ditto every twin is a direct child of the site (flat hierarchy, as in the
// platform's Example Mine). The tree here groups them by the plain attribute
// `section` (the area twin a unit works for), falling back to `_parents`.
const treeParent = (c) => (c ? c.section || c.parent : null);
function buildTree() {
  const kids = {};
  for (const c of S.catalog) { const p = treeParent(c) || '_root'; (kids[p] = kids[p] || []).push(c); }
  const node = (c) => {
    const ch = kids[c.id];
    if (ch && ch.length) {
      const d = el('details');
      if (!treeParent(c)) d.open = true;
      const sm = el('summary', null, `${esc(c.name)} <span class="muted small">(${ch.length})</span>`);
      sm.addEventListener('click', (e) => { if (e.detail === 2) select(c.id); });
      d.appendChild(sm);
      const own = el('div', 'leaf', `<span>⌂ сам узел</span><span class="st">${esc(c.id)}</span>`); own.dataset.id = c.id; own.addEventListener('click', () => select(c.id)); d.appendChild(own);
      for (const x of ch) d.appendChild(node(x));
      return d;
    }
    const l = el('div', 'leaf', `<span>${esc(c.name)}</span><span class="st" data-st="${c.id}"></span>`);
    l.dataset.id = c.id;
    l.addEventListener('click', () => select(c.id));
    return l;
  };
  const t = $('#tree');
  t.innerHTML = '';
  for (const r of kids._root || []) t.appendChild(node(r));
  $('#treeFilter').addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    t.querySelectorAll('.leaf').forEach((l) => { l.style.display = !q || l.textContent.toLowerCase().includes(q) || l.dataset.id.includes(q) ? '' : 'none'; });
    if (q) t.querySelectorAll('details').forEach((d) => (d.open = true));
  });
}
function refreshTreeStates() {
  document.querySelectorAll('[data-st]').forEach((s) => {
    const id = s.dataset.st;
    const t = S.t[id] || {};
    s.textContent = t.state_ru || t.status || t.state || (t.pm10 !== undefined ? num(t.pm10) + ' мкг/м³' : '');
  });
}

// Inspector -----------------------------------------------------------------------
const DASH = {
  'haul-truck': 'bozshakol-haulage', loader: 'bozshakol-haulage', 'water-truck': 'bozshakol-haulage', road: 'bozshakol-haulage',
  drill: 'bozshakol-drill-blast', block: 'bozshakol-drill-blast', crusher: 'bozshakol-plant', conveyor: 'bozshakol-plant',
  'sag-mill': 'bozshakol-plant', 'ball-mill': 'bozshakol-plant', flotation: 'bozshakol-plant', thickener: 'bozshakol-plant',
  tailings: 'bozshakol-plant', 'clay-plant': 'bozshakol-plant', water: 'bozshakol-plant', substation: 'bozshakol-energy',
  'fuel-station': 'bozshakol-energy', workshop: 'bozshakol-maintenance', weather: 'bozshakol-safety',
  'dust-monitor': 'bozshakol-safety', 'slope-radar': 'bozshakol-safety', 'gas-monitor': 'bozshakol-safety', personnel: 'bozshakol-safety',
  stockpile: 'bozshakol-geology', 'waste-dump': 'bozshakol-geology', forecast: 'bozshakol-whatif', control: 'bozshakol-whatif',
  analyzer: 'bozshakol-data-ml', 'seismic-station': 'bozshakol-data-ml', 'mwd-analyzer': 'bozshakol-data-ml',
  laboratory: 'bozshakol-standards', 'power-quality-meter': 'bozshakol-standards', 'energy-profile': 'bozshakol-energy',
};
function select(id) {
  S.selected = id;
  document.querySelectorAll('.tree .leaf').forEach((l) => {
    const on = l.dataset.id === id;
    l.classList.toggle('sel', on);
    if (on) { for (let d = l.parentElement; d && d.id !== 'tree'; d = d.parentElement) if (d.tagName === 'DETAILS') d.open = true; }
  });
  renderInspector();
  if (window.innerWidth <= 1200) showBanner(`${S.byId[id]?.name || id}`, 'warn', 2500);
}
// Equipment passport: a static twin attribute, fetched once per twin and cached.
const PASS = {};
let passOpen = false;
function loadPassport(id) {
  if (id in PASS) return;
  PASS[id] = undefined;
  api(`/things/${NS}:${id}/attributes/passport`).then((p) => { PASS[id] = p && p.status ? p : null; })
    .catch(() => { PASS[id] = null; }).finally(() => { if (S.selected === id) renderInspector(); });
}
function passportHtml(id) {
  const p = PASS[id];
  if (!p) return '';
  const fmt = (v) => (v === null || v === undefined ? '— (не подтверждено)' : typeof v === 'number' ? num(v, Number.isInteger(v) ? 0 : v < 10 ? 2 : 1) : esc(v));
  const specs = Object.values(p.specs || {}).map((x) => `<tr><td>${esc(x.label)}</td><td class="v">${fmt(x.value)} <span class="muted small">${esc(x.unit || '')}</span></td></tr>`).join('');
  const notes = (p.notes || []).map((n) => `<li>${esc(n)}</li>`).join('');
  const src = p.source ? (p.source.url ? `<a target="_blank" rel="noopener" href="${esc(p.source.url)}">${esc(p.source.title)}</a>` : esc(p.source.title)) +
    (p.source.ref ? `<span class="muted"> · ${esc(p.source.ref)}</span>` : '') : '';
  const head = p.model ? `${esc(p.manufacturer)} · <b>${esc(p.model)}</b>${p.variant ? ` · ${esc(p.variant)}` : ''}` : '';
  return `<details class="passport" ${passOpen ? 'open' : ''}><summary>Паспорт оборудования <span class="pstat s-${esc(p.status)}">${esc(p.status_ru)}</span></summary>
    ${head ? `<div class="phead">${head}</div>` : ''}
    ${specs ? `<table>${specs}</table>` : ''}
    ${notes ? `<ul class="pnotes">${notes}</ul>` : ''}
    ${src ? `<div class="psrc">Источник: ${src}</div>` : ''}</details>`;
}
function renderInspector() {
  const id = S.selected;
  if (id) loadPassport(id);
  const box1 = $('#inspector');
  if (!id) return;
  const c = S.byId[id] || { name: id, kind: '' };
  const t = S.t[id] || {};
  const crumbs = [];
  let p = treeParent(c);
  while (p) { const pc = S.byId[p]; crumbs.unshift(`<a data-id="${p}">${esc(pc?.name || p)}</a>`); p = treeParent(pc); }
  const attrs = S.byId[id] || {};
  const extra = ['type', 'model', 'dataset', 'ml_model', 'face', 'role', 'payload_t', 'bucket_m3', 'area'].filter((k) => attrs[k] !== undefined)
    .map((k) => `<span>${esc(k)}: ${esc(attrs[k])}</span>`).join('');
  const dash = DASH[c.kind] || 'bozshakol-overview';
  let rows = '';
  for (const [k, val] of Object.entries(t)) {
    if (k === 'events' || k === 'frames') continue;
    const lab = S.labels[k] || k;
    const unit = S.units[id]?.[k] || '';
    const sv = typeof val === 'number' ? num(val, Number.isInteger(val) ? 0 : Math.abs(val) < 10 ? 3 : 1) : typeof val === 'boolean' ? (val ? 'да' : 'нет') : esc(val);
    rows += `<tr><td title="${esc(k)}">${esc(lab)}</td><td class="v">${sv} <span class="muted small">${esc(unit)}</span></td></tr>`;
  }
  const sparkKey = ['throughput', 'payload', 'cm_brake_oil', 'cm_hydraulic_oil', 'cm_compressor_temp', 'speed', 'power_mw', 'pm10', 'rop', 'level_kt', 'recovery', 'co', 'w2_velocity', 'mill_tph', 'stock_kt', 'moisture', 'total_mw', 'temperature', 'bays_busy', 'dig_rate', 'tonnes', 'remaining']
    .find((k) => typeof t[k] === 'number');
  box1.innerHTML = `<div class="label">${esc(c.kind || '')}</div><h2>${esc(c.name)}</h2>
    <div class="crumbs">${crumbs.join(' › ') || '—'}</div>
    <div class="attrs"><span class="mono">${NS}:${esc(id)}</span>${extra}</div>
    ${sparkKey ? `<div class="label">${esc(S.labels[sparkKey] || sparkKey)} — последние минуты</div><svg class="spark" viewBox="0 0 300 56" preserveAspectRatio="none"><path id="sparkPath" fill="none" stroke="#d4824a" stroke-width="2"/></svg>` : ''}
    <div class="links"><a target="_blank" href="${GRAFANA}/d/${dash}?var-twin=${NS}:${id}">Grafana</a>
      <a target="_blank" href="${API}/things/${NS}:${id}">JSON двойника (Ditto)</a></div>
    ${passportHtml(id)}
    ${linksHtml(id)}
    <div class="label">Телеметрия</div>
    <table>${rows}</table>`;
  box1.querySelector('details.passport')?.addEventListener('toggle', (e) => { passOpen = e.target.open; });
  box1.querySelectorAll('.links-box a').forEach((a) => a.addEventListener('click', () => select(a.dataset.id)));
  box1.querySelectorAll('.crumbs a').forEach((a) => a.addEventListener('click', () => select(a.dataset.id)));
  if (sparkKey) {
    const h = (S.hist[id]?.[sparkKey] || []).slice(-150);
    if (h.length > 1) {
      const mn = Math.min(...h), mx = Math.max(...h), span = mx - mn || 1;
      const d = h.map((y, i) => `${i ? 'L' : 'M'}${(i / (h.length - 1)) * 300},${52 - ((y - mn) / span) * 48}`).join(' ');
      box1.querySelector('#sparkPath').setAttribute('d', d);
    }
  }
}

// Lerchs-Grossmann pit shells ------------------------------------------------------------
// Nested optimal pits (revenue factor 0.35 ... 1.0) from tools/pit_optimize.py, stored
// in the attribute pit_shells of each pit twin. Surface outlines of every shell
// lie on the ground as coloured ribbons (inner = first stages); the bench outlines
// of the ultimate pit are drawn see-through, since most of them are still in rock.
const shells = { group: new THREE.Group() };
function buildShells() {
  scene.add(shells.group);
  shells.group.visible = false;
  const inner = new THREE.Color('#ffe08a'), outer = new THREE.Color('#e5533c');
  for (const key of Object.keys(S.site.layout.pits || { central: 1 })) {
    const id = `pit-${key}`, sh = S.byId[id]?.pit_shells;
    if (!sh?.shells?.length) continue;
    const n = sh.shells.length;
    sh.shells.forEach((s, i) => {
      const col = inner.clone().lerp(outer, n > 1 ? i / (n - 1) : 1);
      const last = i === n - 1;
      for (const lv of s.levels) {
        for (const loop of lv.loops) {
          if (lv.z >= -0.1) {
            // surface outline: a flat ribbon just above the ground
            const pts = loop.concat([loop[0]]).map(([x, y]) => P(x, y, 0).setY(1.2 + i * 0.25));
            const curve = new THREE.CatmullRomCurve3(pts, false, 'catmullrom', 0.05);
            const m = new THREE.Mesh(new THREE.TubeGeometry(curve, Math.min(600, pts.length * 4), last ? 4.5 : 3, 4, false),
              new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: last ? 0.95 : 0.8, depthWrite: false }));
            m.renderOrder = 4;
            shells.group.add(m);
          } else if (last) {
            const g = new THREE.BufferGeometry().setFromPoints(loop.concat([loop[0]]).map(([x, y]) => P(x, y, lv.z)));
            const l = new THREE.Line(g, new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: 0.45, depthTest: false }));
            l.renderOrder = 6;
            shells.group.add(l);
          }
        }
      }
    });
    const u = sh.shells[n - 1], top = u.levels[0]?.loops?.[0];
    if (!top) continue;
    const north = top.reduce((a, b) => (b[1] > a[1] ? b : a));
    addTag('lg-' + key, `<b>Контур LG · ${esc(sh.name)}</b><br>руда ${num(u.ore_mt, 0)} Мт · ${num(u.cu_pct, 2)} % Cu · вскрыша/руда ${num(u.strip_t_t, 2)} т/т · ${u.depth_m} м`,
      () => (shells.group.visible ? P(north[0], north[1], 0).setY(30) : null), { twin: id, cls: 'small', prio: 6, show: () => shells.group.visible });
  }
}

// Flowsheet ---------------------------------------------------------------------------
const FLOW = [
  { id: 'pit', x: 10, label: 'Карьеры Ц / В', twin: 'pit-central', val: () => `${num(v('pit-central', 'loaders_working'))}/4 · ${num(v('pit-east', 'loaders_working'))}/2 экск.`, sub: () => `вскрыто ${num(v('pit-central', 'exposed_months'), 1)} / ${num(v('pit-east', 'exposed_months'), 1)} мес`, warn: () => Math.min(v('pit-central', 'exposed_months', 9), v('pit-east', 'exposed_months', 9)) < 1.5 },
  { id: 'trucks', x: 190, label: 'Самосвалы', twin: 'haulage', val: () => `${num(v('haulage', 'productivity_tph'))} т/ч`, sub: () => `в работе ${num(v('site', 'trucks_working'))}/26` },
  { id: 'gc', x: 370, label: 'ККД-1', twin: 'gc-01', val: () => `${num(v('gc-01', 'throughput'))} т/ч`, sub: () => `броня ${num(v('gc-01', 'mantle_wear'))}%`, bad: () => ['down', 'mantle_change'].includes(v('gc-01', 'state')) },
  { id: 'cv', x: 550, label: 'Конвейер', twin: 'cv-01', val: () => `${num(v('cv-01', 'load_tph'))} т/ч`, sub: () => `${num(v('cv-01', 'on_belt_t'))} т на ленте` },
  { id: 'cos', x: 730, label: 'Склад КД', twin: 'cos-01', val: () => `${num(v('cos-01', 'level_kt'), 1)} кт`, sub: () => `запас ${num(v('cos-01', 'hours_cover'), 1)} ч`, warn: () => v('cos-01', 'hours_cover', 9) < 3 },
  { id: 'sag', x: 910, label: 'МПСИ', twin: 'sag-01', val: () => `${num(v('sag-01', 'throughput'))} т/ч`, sub: () => `${num(v('sag-01', 'power_mw'), 1)} МВт · ${num(v('sag-01', 'specific_energy'), 1)} кВт·ч/т`, bad: () => v('sag-01', 'state') === 'starved' },
  { id: 'bm', x: 1090, label: 'ШМ ×2', twin: 'bm-01', val: () => `P80 ${num(v('bm-01', 'p80'))} мкм`, sub: () => `${num(v('ss-220', 'load_bm'), 1)} МВт` },
  { id: 'fl', x: 1270, label: 'Флотация', twin: 'fl-r', val: () => `ε ${num(v('fl-r', 'recovery'), 1)}%`, sub: () => `τ ${num(v('fl-r', 'residence_min'), 1)} мин · глина ${num(v('fl-r', 'feed_clay'), 1)}%` },
  { id: 'conc', x: 1450, label: 'Концентрат', twin: 'fl-c', val: () => `${num(v('fl-c', 'conc_tph'), 1)} т/ч`, sub: () => `${num(v('fl-c', 'conc_grade'), 1)}% Cu · ${num(v('fl-c', 'cu_tph'), 2)} т Cu/ч` },
];
function buildFlow() {
  const svg = $('#flowsheet');
  let h = '';
  for (let i = 0; i < FLOW.length - 1; i++) {
    const a = FLOW[i], b = FLOW[i + 1];
    h += `<path class="pipe" d="M${a.x + 140},48 L${b.x},48"/><path class="flowline" id="fl-${a.id}" d="M${a.x + 140},48 L${b.x},48"/>`;
  }
  h += `<path class="pipe" d="M260,78 L260,118 L330,118"/><text x="336" y="122" class="lbl" id="fv-dump">Отвал</text>`;
  h += `<path class="pipe" d="M1340,78 L1340,118 L1380,118"/><text x="1386" y="122" class="lbl" id="fv-tails">Хвосты</text>`;
  h += `<text x="10" y="140" class="lbl" id="fv-clay">Глинистая фабрика</text>`;
  for (const n of FLOW) {
    h += `<g data-twin="${n.twin}" style="cursor:pointer"><rect class="node" id="fn-${n.id}" x="${n.x}" y="18" width="140" height="60" rx="8"/>
      <text x="${n.x + 10}" y="36">${n.label}</text><text x="${n.x + 10}" y="55" class="val" id="fv-${n.id}">—</text>
      <text x="${n.x + 10}" y="71" class="lbl" id="fs-${n.id}">—</text></g>`;
  }
  svg.innerHTML = h;
  svg.querySelectorAll('g[data-twin]').forEach((g) => g.addEventListener('click', () => select(g.dataset.twin)));
}
const flowOffset = {};
function updateFlow(dt) {
  for (const n of FLOW) {
    const a = document.getElementById('fv-' + n.id), b = document.getElementById('fs-' + n.id), r = document.getElementById('fn-' + n.id);
    if (!a) continue;
    a.textContent = n.val(); b.textContent = n.sub();
    r.classList.toggle('down', !!(n.bad && n.bad()));
    r.classList.toggle('warn', !!(n.warn && n.warn()));
  }
  const rates = { pit: v('haulage', 'productivity_tph', 0), trucks: v('gc-01', 'throughput', 0), gc: v('cv-01', 'load_tph', 0),
    cv: v('cv-01', 'load_tph', 0), cos: v('sag-01', 'throughput', 0), sag: v('sag-01', 'throughput', 0), bm: v('sag-01', 'throughput', 0), fl: v('fl-c', 'conc_tph', 0) * 40 };
  for (const [k, rate] of Object.entries(rates)) {
    const p = document.getElementById('fl-' + k);
    if (!p) continue;
    flowOffset[k] = ((flowOffset[k] || 0) - dt * rate / 60) % 1000;
    p.style.strokeDashoffset = flowOffset[k];
    p.style.opacity = rate > 50 ? 1 : 0.15;
  }
  const dumpEl = document.getElementById('fv-dump');
  if (dumpEl) dumpEl.textContent = `Отвалы: Сев. ${num(v('wd-01', 'dumped_kt'), 0)} · Вост. ${num(v('wd-02', 'dumped_kt'), 0)} кт · забаланс ${num(v('lg-01', 'stock_kt'), 0)} кт`;
  const tl = document.getElementById('fv-tails');
  if (tl) tl.textContent = `Хвосты ${num(v('fl-r', 'tails_grade'), 3)}% Cu → ХХ`;
  const cl = document.getElementById('fv-clay');
  if (cl) cl.textContent = `Глинистая фабрика: ${num(v('cp-01', 'throughput'))} т/ч, ε ${num(v('cp-01', 'recovery'), 1)}% · Вода: ${num(v('water-01', 'fresh_m3h'))} м³/ч свежей`;
}

// ---------------------------------------------------------------- polling
S.units = {};
let polling = false;
async function poll() {
  if (polling || !S.catalog.length) return;
  polling = true;
  try {
    const ids = S.catalog.map((c) => `${NS}:${c.id}`).join(',');
    const things = await api(`/things?ids=${encodeURIComponent(ids)}&fields=thingId,features`);
    const now = Date.now();
    for (const th of things) {
      const name = th.thingId.split(':')[1];
      const vals = {}, units = {};
      for (const [k, f] of Object.entries(th.features || {})) {
        const pr = f.properties || {};
        vals[k] = pr.value;
        if (pr.unit) units[k] = pr.unit;
        if (typeof pr.value === 'number') {
          const h = ((S.hist[name] = S.hist[name] || {})[k] = S.hist[name][k] || []);
          h.push(pr.value); if (h.length > 300) h.shift();
        }
      }
      S.t[name] = vals; S.units[name] = units;
    }
    if (S.lastOk) pollGap = THREE.MathUtils.clamp(pollGap * 0.8 + (now - S.lastOk) * 0.2, 800, 6000);
    S.lastOk = now;
    $('#conn').className = 'conn ok';
    $('#connText').textContent = `Ditto: ${things.length} двойников · ${new Date().toLocaleTimeString('ru-RU')}`;
    dynamicTags();
    refreshTagText();
    renderKpis();
    renderEvents();
    renderForecast();
    renderPlan();
    syncPlanForm();
    if (webgl) fcIngest();
    syncManualForm();
    refreshTreeStates();
    renderInspector();
    S.firstData = true;
  } catch (e) {
    $('#conn').className = 'conn bad';
    $('#connText').textContent = 'нет связи с Ditto: ' + e.message;
  } finally {
    polling = false;
  }
}

// ---------------------------------------------------------------- 2D fallback (no WebGL)
let c2d = null;
function setup2d() {
  const cv = document.createElement('canvas');
  cv.id = 'scene2d'; cv.style.cssText = 'width:100%;height:100%;display:block;cursor:crosshair';
  canvas.replaceWith(cv);
  c2d = { cv, ctx: cv.getContext('2d'), map: null, pts: [] };
  cv.addEventListener('click', (e) => {
    const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    let best = null, bd = 14;
    for (const p of c2d.pts) { const d = Math.hypot(p.x - mx, p.y - my); if (d < bd) { bd = d; best = p.id; } }
    if (best) select(best);
  });
  $('#noWebgl').textContent = 'WebGL недоступен — показан 2D-план рудника по данным двойников (клик по объекту — инспектор).';
}
function draw2d() {
  const { cv, ctx } = c2d;
  const r = cv.getBoundingClientRect();
  if (cv.width !== r.width || cv.height !== r.height) { cv.width = r.width; cv.height = r.height; }
  const X0 = -1400, X1 = 5200, Y0 = -2300, Y1 = 1800;
  const k = Math.min(cv.width / (X1 - X0), cv.height / (Y1 - Y0));
  const ox = (cv.width - (X1 - X0) * k) / 2, oy = (cv.height - (Y1 - Y0) * k) / 2;
  const T = (x, y) => [ox + (x - X0) * k, oy + (Y1 - y) * k];
  ctx.fillStyle = '#b9a77e'; ctx.fillRect(0, 0, cv.width, cv.height);
  const pit0 = S.site.layout.pit;
  for (const q of Object.values(S.site.layout.pits || { central: { cx: 0, cy: 0, a: pit0.a, b: pit0.b, n: pit0.n } })) {
    for (let b = 0; b <= q.n; b += 1) {
      const [cx, cy] = T(q.cx, q.cy);
      ctx.beginPath(); ctx.ellipse(cx, cy, (q.a - pit0.step * b) * k, (q.b - pit0.step * b) * k, 0, 0, Math.PI * 2);
      ctx.fillStyle = `rgb(${170 - b * 6},${140 - b * 6},${105 - b * 4})`; ctx.fill();
    }
  }
  for (const e of S.site.layout.edges) {
    const st = v(e.road, 'status_code', 'open');
    ctx.strokeStyle = ROAD_COLORS[st]; ctx.lineWidth = e.road === 'road-faces' ? 2 : 4; ctx.beginPath();
    e.pts.forEach((p, i) => { const [x, y] = T(p[0], p[1]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
  }
  c2d.pts = [];
  ctx.font = '11px sans-serif';
  const facs = { crusher: 'gc-01', cos: 'cos-01', sag: 'sag-01', flot_r: 'fl-r', th_t: 'th-t', tsf: 'tsf-01', clay_plant: 'cp-01', workshop: 'ws-01', fuel: 'fs-01', substation: 'ss-220', dump: 'wd-01', dump_e: 'wd-02', lg: 'lg-01', radar: 'sr-01' };
  for (const [f, id] of Object.entries(facs)) {
    const p = S.site.layout.facilities[f]; if (!p) continue;
    const [x, y] = T(p[0], p[1]);
    ctx.fillStyle = '#39434e'; ctx.fillRect(x - 6, y - 6, 12, 12);
    ctx.fillStyle = '#0e1114'; ctx.fillText(S.byId[id]?.name?.split(' ')[0] || id, x + 8, y + 4);
    c2d.pts.push({ x, y, id });
  }
  for (const it of S.catalog) {
    const t = S.t[it.id]; if (!t || t.x === undefined) continue;
    const [x, y] = T(t.x, t.y);
    if (it.kind === 'block') { if (t.state === 'depleted') continue; ctx.fillStyle = BLOCK_COLORS[t.state]; ctx.fillRect(x - 6, y - 4, 12, 8); }
    else if (it.kind === 'haul-truck') { ctx.fillStyle = TRUCK_COLORS[t.state] || '#888'; ctx.beginPath(); ctx.arc(x, y, 4, 0, 7); ctx.fill(); }
    else if (it.kind === 'loader') { ctx.fillStyle = '#f08a24'; ctx.fillRect(x - 5, y - 5, 10, 10); ctx.fillStyle = '#0e1114'; ctx.fillText(it.id.toUpperCase(), x + 7, y - 6); }
    else if (it.kind === 'drill') { ctx.fillStyle = '#c43e2f'; ctx.beginPath(); ctx.moveTo(x, y - 6); ctx.lineTo(x + 5, y + 4); ctx.lineTo(x - 5, y + 4); ctx.fill(); }
    else if (it.kind === 'personnel' || it.kind === 'light-vehicle') { ctx.fillStyle = t.alert ? '#e5534b' : '#f5d000'; ctx.beginPath(); ctx.arc(x, y, 3, 0, 7); ctx.fill(); }
    else continue;
    c2d.pts.push({ x, y, id: it.id });
  }
  if (v('safety', 'plume_active')) { const [x, y] = T(v('safety', 'plume_x'), v('safety', 'plume_y')); ctx.fillStyle = 'rgba(150,130,100,.35)'; ctx.beginPath(); ctx.arc(x, y, v('safety', 'plume_r', 60) * k, 0, 7); ctx.fill(); }
}

// ---------------------------------------------------------------- main loop
function resize() {
  if (!webgl) return;
  const r = canvas.parentElement.getBoundingClientRect();
  env.resize(r.width, r.height);
  camera.aspect = r.width / Math.max(1, r.height);
  camera.updateProjectionMatrix();
}

// Model clock -> hour of day for the sun (interpolated between polls).
const clock = { h: 12, at: 0, rate: 10 };
function simHour(now) {
  if (clock.fixed !== undefined) return clock.fixed;
  const st = v('site', 'sim_time');
  if (st && st !== clock.raw) {
    const m = /(\d+):(\d+)$/.exec(st);
    if (m) { clock.h = +m[1] + +m[2] / 60; clock.at = now; clock.raw = st; clock.rate = +v('site', 'sim_speed', 10) || 10; }
  }
  return (clock.h + ((now - clock.at) / 3.6e6) * clock.rate * (clock.at ? 1 : 0)) % 24;
}

let fpsAcc = 0, fpsN = 0;
// ---------------------------------------------------------------- relations between twins
// The graph comes from the twins: site.flow_graph (static edges) and the
// link_* features (truck -> loader -> block, truck -> destination). Arcs carry
// a moving dash in the direction of the flow.
const REL_COLORS = { feeds: '#f0a040', water: '#45c8f0', power: '#7f8cff', fuel: '#f2d14b', maintains: '#b0b8c0',
  monitors: '#6fe0b0', samples: '#6fe0b0', digs: '#f0a040', analog_of: '#c78cf0', scenario: '#ffffff', dispatch: '#ffd166' };
const REL_RU_UI = { dispatch: 'назначен (живая связь)' };
const linkMat = (color) => new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  uniforms: { time: { value: 0 }, color: { value: new THREE.Color(color) }, len: { value: 100 } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
  fragmentShader: `uniform float time; uniform vec3 color; uniform float len; varying vec2 vUv;
    void main(){ float d = fract(vUv.x * len / 60.0 - time * 0.8); float a = 0.35 + 0.65 * smoothstep(0.0, 0.15, d) * (1.0 - smoothstep(0.45, 0.6, d));
      gl_FragColor = vec4(color, a * 0.85); }`,
});
const links = { stat: new THREE.Group(), sel: new THREE.Group(), mats: [], selKey: '', t: 0 };
function twinPos(id) {
  const F = S.site.layout.facilities;
  if (id === 'cv-01') return P(...F.crusher).lerp(P(...F.cos), 0.5);
  if (['pit-central', 'drill-blast'].includes(id)) return P(0, 150, -60);
  if (id.startsWith('pit-') && S.site.layout.pits?.[id.slice(4)]) { const q = S.site.layout.pits[id.slice(4)]; return P(q.cx, q.cy + q.b * 0.25, -30); }
  if (id === 'haulage') return P(1300, 200, 0);
  const o = objs[id];
  return o && o.visible !== false ? o.position.clone() : null;
}
function arc(a, b, color, radius = 3) {
  const dist = a.distanceTo(b);
  const mid = a.clone().lerp(b, 0.5); mid.y = Math.max(a.y, b.y) + 40 + dist * 0.22;
  const curve = new THREE.QuadraticBezierCurve3(a.clone().setY(a.y + 8), mid, b.clone().setY(b.y + 8));
  const m = linkMat(color); m.uniforms.len.value = dist;
  links.mats.push(m);
  const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, Math.max(12, Math.min(64, Math.round(dist / 40))), radius, 6), m);
  mesh.renderOrder = 5;
  return mesh;
}
function edgesOf(id) {
  const out = [];
  for (const [a, rel, b] of S.site?.flow_graph?.edges || []) if (a === id || b === id) out.push([a, rel, b]);
  const t = S.t[id] || {};
  const strip = (x) => (x || '').split(':').pop();
  if (t.link_loader) out.push([id, 'dispatch', strip(t.link_loader)]);
  if (t.link_destination) out.push([id, 'feeds', strip(t.link_destination)]);
  if (t.link_block) out.push([id, 'digs', strip(t.link_block)]);
  for (const tr of (t.link_trucks || '').split(',').filter(Boolean)) out.push([strip(tr), 'dispatch', id]);
  const seen = new Set();
  return out.filter(([a, rel, b]) => { const k = a + '|' + rel + '|' + b; if (seen.has(k)) return false; seen.add(k); return true; });
}
function buildLinks() {
  scene.add(links.stat); scene.add(links.sel);
  for (const [a, rel, b] of S.site?.flow_graph?.edges || []) {
    if (!['feeds', 'water', 'power'].includes(rel)) continue;
    const pa = twinPos(a), pb = twinPos(b);
    if (!pa || !pb || objs[a]?.userData.kind || objs[b]?.userData.kind) continue;   // mobile fleet: only for the selection
    links.stat.add(arc(pa, pb, REL_COLORS[rel], rel === 'power' ? 2.2 : 3.2));
  }
  links.stat.visible = false;
}
function updateLinks(dt) {
  links.t += dt;
  for (const m of links.mats) m.uniforms.time.value = links.t;
  links.stat.visible = !!$('#lyrLinks')?.checked;
  shells.group.visible = !!$('#lyrShells')?.checked;
  const id = S.selected;
  if (!id) { if (links.sel.children.length) { links.sel.clear(); links.selKey = ''; } return; }
  // rebuild the selection's arcs a few times per second (mobile ends move)
  if ((links.frame = (links.frame || 0) + 1) % 12 !== 0 && links.selKey === id) return;
  links.selKey = id;
  for (const c of links.sel.children) { c.geometry.dispose(); links.mats.splice(links.mats.indexOf(c.material), 1); c.material.dispose(); }
  links.sel.clear();
  for (const [a, rel, b] of edgesOf(id)) {
    const pa = twinPos(a), pb = twinPos(b);
    if (pa && pb && pa.distanceTo(pb) > 5) links.sel.add(arc(pa, pb, REL_COLORS[rel] || '#ffffff', 2.6));
  }
}
function linksHtml(id) {
  const rows = edgesOf(id);
  if (!rows.length) return '';
  const name = (x) => esc(S.byId[x]?.name || x);
  const lab = (rel) => REL_RU_UI[rel] || S.site.flow_graph?.relation_types?.[rel] || rel;
  const li = rows.map(([a, rel, b]) => {
    const other = a === id ? b : a, dir = a === id ? '→' : '←';
    return `<li><i style="background:${REL_COLORS[rel] || '#fff'}"></i>${dir} ${esc(lab(rel))}: <a data-id="${esc(other)}">${name(other)}</a></li>`;
  }).join('');
  return `<details class="links-box" open><summary>Связи (${rows.length})</summary><ul>${li}</ul></details>`;
}

// ---------------------------------------------------------------- what-if consequences on the scene
// The forecaster sends spatial frames every 4 h of the 48 h horizon for both
// runs (whatif.frames). Each key object gets two columns: the baseline as a
// pale ghost and the scenario coloured by whether it is better or worse, with
// a label "base → scenario (Δ)". The slider scrubs the 48 hours.
const FC_META = {
  'cos-01': ['Склад КД', 'кт', 0], 'lg-01': ['Склад забаланса', 'кт', 0], 'wd-01': ['Вскрыша, Сев. отвал', 'кт', 0],
  'sag-01': ['Переработано ОФ', 'кт', 1], 'th-c': ['Медь в концентрате', 'т', 1], 'cp-01': ['Глинистая ф-ка', 'кт', 1],
  'ss-220': ['Электроэнергия', 'МВт·ч', -1], 'fs-01': ['Дизтопливо', 'м³', -1], 'gc-01': ['Бункер ККД', '%', 0],
  haulage: ['Самосвалов в работе', 'шт', 1], 'sh-01': ['SH-01 отгрузил', 'кт', 1], 'sh-02': ['SH-02 отгрузил', 'кт', 1],
  'sh-03': ['SH-03 отгрузил', 'кт', 1], 'ld-01': ['LD-01 отгрузил', 'кт', 1],
  'sh-04': ['SH-04 отгрузил', 'кт', 1], 'ex-01': ['EX-01 отгрузил', 'кт', 1], 'wd-02': ['Вскрыша, Вост. отвал', 'кт', 0],
  'pit-central': ['Вскрытые запасы Центр.', 'мес', 1], 'pit-east': ['Вскрытые запасы Вост.', 'мес', 1],
};
const FC_DOWN = ['breakdown', 'down', 'mantle_change', 'starved', 'slope_hold'];
const fc3 = { data: null, raw: '', on: false, t: 48, play: false, cols: {}, group: new THREE.Group() };
function fcValue(run, id, t) {
  const fr = fc3.data?.[run];
  if (!fr?.length) return null;
  const x = Math.min(fr.length - 1, t / fc3.data.step_h), i = Math.floor(x), f = x - i;
  const a = fr[i]?.[id], b = fr[Math.min(fr.length - 1, i + 1)]?.[id];
  if (!a) return null;
  return { v: a.v + ((b?.v ?? a.v) - a.v) * f, s: (f < 0.5 ? a.s : b?.s) || a.s, down: a.down, queue: a.queue };
}
function fcBuild() {
  scene.add(fc3.group);
  const ghost = new THREE.MeshStandardMaterial({ color: '#dfe6ee', transparent: true, opacity: 0.38, roughness: 0.6, depthWrite: false });
  for (const id of Object.keys(FC_META)) {
    const g = new THREE.Group();
    const geo = new THREE.BoxGeometry(1, 1, 1); geo.translate(0, 0.5, 0);
    const base = new THREE.Mesh(geo, ghost);
    const scen = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: '#f0a56c', emissive: '#f0a56c', emissiveIntensity: 0.25, roughness: 0.5 }));
    base.position.x = -16; scen.position.x = 16;
    g.add(base, scen);
    fc3.group.add(g);
    fc3.cols[id] = { g, base, scen };
    addTag('fc-' + id, '', () => (fc3.on && fc3.cols[id].g.visible ? fc3.cols[id].g.position.clone().add(new THREE.Vector3(0, fc3.cols[id].top + 26, 0)) : null),
      { twin: id === 'haulage' ? null : id, cls: 'small fc', prio: 7, show: () => fc3.on });
  }
  fc3.group.visible = false;
  $('#fc3dOpen').addEventListener('click', () => { fcShow(true); if (fc3.on) setView('overview'); });
  $('#fc3dClose').addEventListener('click', () => fcShow(false));
  $('#fc3dT').addEventListener('input', (e) => { fc3.t = +e.target.value; fc3.play = false; $('#fc3dPlay').textContent = '▶'; });
  $('#fc3dPlay').addEventListener('click', () => {
    fc3.play = !fc3.play; $('#fc3dPlay').textContent = fc3.play ? '❚❚' : '▶';
    if (fc3.play && fc3.t >= 48) fc3.t = 0;
  });
}
function fcShow(on) {
  fc3.on = on && !!fc3.data;
  $('#fc3d').classList.toggle('hidden', !fc3.on);
  fc3.group.visible = fc3.on;
  if (fc3.on) $('#fc3dScen').textContent = v('whatif', 'scenario', '');
}
function fcIngest() {
  const raw = v('whatif', 'frames', '');
  const ready = v('whatif', 'status', '') === 'готов';
  // while a new scenario is being computed the old frames are stale
  if (fc3.on) $('#fc3dScen').textContent = ready ? v('whatif', 'scenario', '') : 'пересчёт прогноза…';
  if (!ready || !raw || raw === fc3.raw) return;
  fc3.raw = raw;
  try { fc3.data = JSON.parse(raw); } catch (e) { fc3.data = null; return; }
  // auto-open when the operator has just chosen a scenario
  const scenario = v('whatif', 'scenario', 'базовый режим');
  if (scenario !== 'базовый режим' && !fc3.on && webgl) { fc3.t = 0; fc3.play = true; $('#fc3dPlay').textContent = '❚❚'; fcShow(true); }
  if (fc3.on) $('#fc3dScen').textContent = scenario;
}
function fcUpdate(dt) {
  if (!fc3.on || !fc3.data) return;
  if (fc3.play) { fc3.t = Math.min(48, fc3.t + dt * 4); if (fc3.t >= 48) { fc3.play = false; $('#fc3dPlay').textContent = '▶'; } }
  $('#fc3dT').value = fc3.t; $('#fc3dH').textContent = `+${Math.round(fc3.t)} ч`;
  const H = DIORAMA ? 340 : 300;
  const W = THREE.MathUtils.clamp(orbit.dist * 0.011, 24, 110);   // readable from the overview and close up
  for (const [id, [label, unit, dir]] of Object.entries(FC_META)) {
    const col = fc3.cols[id];
    const pos = id === 'haulage' ? P(1350, 420, 0) : twinPos(id);
    const b = fcValue('baseline', id, fc3.t), sc = fcValue('scenario', id, fc3.t);
    col.g.visible = !!(pos && b && sc);
    if (!col.g.visible) continue;
    col.g.position.copy(pos).add(new THREE.Vector3(W * 1.8, 0, 0));
    col.g.rotation.set(0, Math.atan2(camera.position.x - col.g.position.x, camera.position.z - col.g.position.z), 0);
    let mx = 1e-6;
    for (const run of ['baseline', 'scenario']) for (const fr of fc3.data[run]) mx = Math.max(mx, Math.abs(fr[id]?.v || 0));
    const hb = Math.max(2, Math.abs(b.v) / mx * H), hs = Math.max(2, Math.abs(sc.v) / mx * H);
    col.base.scale.set(W, hb, W); col.scen.scale.set(W, hs, W);
    col.base.position.x = -W * 0.62; col.scen.position.x = W * 0.62;
    col.top = Math.max(hb, hs);
    const d = sc.v - b.v, rel = Math.abs(b.v) > 1e-6 ? d / Math.abs(b.v) * 100 : 0;
    const down = FC_DOWN.includes(sc.s);
    const color = down ? '#e5534b' : Math.abs(rel) < 0.5 || !dir ? '#f0a56c' : d * dir > 0 ? '#4fbf7a' : '#e5534b';
    col.scen.material.color.set(color); col.scen.material.emissive.set(color);
    const t = tags['fc-' + id];
    if (t) {
      const cls = Math.abs(rel) < 0.5 ? '' : (dir && d * dir > 0 ? 'up' : dir ? 'dn' : '');
      const n = Math.abs(b.v) >= 100 ? 0 : 1;
      const extra = id === 'haulage' && sc.down !== undefined ? ` · в ремонте ${sc.down}` : sc.s && sc.s !== b.s ? ` · ${esc(LOADER_STATE_UI[sc.s] || sc.s)}` : '';
      const html = `<b>${esc(label)}</b> ${num(b.v, n)} → ${num(sc.v, n)} ${esc(unit)} <span class="${cls}">${rel > 0 ? '+' : ''}${num(rel, 1)}%</span>${extra}`;
      if (t.el.innerHTML !== html) { t.el.innerHTML = html; t.w = 0; }
    }
  }
}
const LOADER_STATE_UI = { breakdown: 'отказ', down: 'остановлена', mantle_change: 'замена брони', starved: 'нет питания', slope_hold: 'запрет под бортом',
  loading: 'погрузка', waiting: 'ожидание', running: 'работает' };

function updateSelection(time) {
  const o = S.selected && objs[S.selected];
  if (!o || !o.visible || o === objs.site) { dyn.sel.visible = false; return; }
  const kind = o.userData.kind || S.byId[S.selected]?.kind;
  let rad = ['analyzer', 'seismic-station', 'mwd-analyzer', 'energy-profile', 'dust-monitor', 'weather', 'slope-radar'].includes(kind) ? 26 : kind === 'haul-truck' || kind === 'water-truck' ? 32 : kind === 'loader' ? 48 : kind === 'drill' ? 30 : kind === 'personnel' || kind === 'light-vehicle' ? 18 : kind === 'block' ? 70 : 85;
  dyn.sel.visible = true;
  dyn.sel.position.set(o.position.x, o.position.y + 1.5, o.position.z);
  if (DIORAMA && SCALE[kind]) rad *= SCALE[kind] / 1.6;
  dyn.sel.scale.setScalar(rad * (1 + 0.04 * Math.sin(time * 3)));
  dyn.selInner.rotation.z = time * 0.9;
}
window.addEventListener('resize', resize);

let last = performance.now();
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  if (tween) {
    const f = Math.min(1, (now - tween.t0) / tween.dur), e = f < 0.5 ? 2 * f * f : 1 - (-2 * f + 2) ** 2 / 2;
    orbit.target.lerpVectors(tween.from.target, tween.to.t, e);
    orbit.dist = tween.from.dist + (tween.to.dist - tween.from.dist) * e;
    orbit.theta = tween.from.theta + (tween.to.theta - tween.from.theta) * e;
    orbit.phi = tween.from.phi + (tween.to.phi - tween.from.phi) * e;
    if (f >= 1) tween = null;
    syncGoal();
  } else dampCamera(dt);
  if (S.follow && S.selected && objs[S.selected]) goal.target.lerp(objs[S.selected].position, 0.12);
  if (S.ready) {
    updateDynamic(dt);
    updateEffects(dt, now / 1000);
    if (webgl) { updateLinks(dt); fcUpdate(dt); }
    updateFlow(dt);
    if (webgl) updateSelection(now / 1000);
    // Attract mode: after two idle minutes the guided tour starts by itself.
    if (tour && !tour.running && !NO_TOUR && now - lastInput > 120000) tour.start(0);
  }
  placeCamera();
  if (webgl) {
    env.setWeather(v('wx-01', 'rain', 0));
    env.setHour(simHour(now));
    env.update(orbit.target, orbit.dist);
    env.sky.position.copy(camera.position);
    MD.setNight(env.night, now / 1000);
    for (const m of masts) if (m.userData.halo) m.userData.halo.quaternion.copy(camera.quaternion);
    env.render();
    updateTags();
    fpsAcc += dt; fpsN++;
    if (fpsAcc > 2) { window.__fps = Math.round(fpsN / fpsAcc); fpsAcc = 0; fpsN = 0; }
  } else if (c2d && S.ready) draw2d();
  requestAnimationFrame(frame);
}

let tour = null;
const NO_TOUR = new URLSearchParams(location.search).has('notour');
async function boot() {
  buildFlow();
  try { S.presets = await (await fetch('presets.json', { cache: 'no-store' })).json(); } catch (e) { S.presets = {}; }
  let site = null;
  for (let i = 0; !site; i++) {
    try { site = await api(`/things/${NS}:site?fields=attributes`); }
    catch (e) {
      $('#conn').className = 'conn bad';
      $('#connText').textContent = `ждём двойников в Ditto (${e.message})…`;
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
  S.site = site.attributes;
  S.catalog = S.site.catalog || [];
  S.labels = S.site.feature_labels || {};
  S.defaults = S.site.control_defaults || {};
  for (const c of S.catalog) S.byId[c.id] = { ...c };
  // Attributes of the things that carry geometry or labels.
  try {
    const ids = ['sr-01', 'whatif'].concat(S.catalog.filter((c) => !['haul-truck', 'block', 'road', 'personnel'].includes(c.kind)).map((c) => c.id));
    const th = await api(`/things?ids=${encodeURIComponent([...new Set(ids)].map((i) => `${NS}:${i}`).join(','))}&fields=thingId,attributes`);
    for (const x of th) { const n = x.thingId.split(':')[1]; S.byId[n] = { ...S.byId[n], ...x.attributes, id: n, parent: S.byId[n]?.parent, section: S.byId[n]?.section, name: x.attributes.name }; }
  } catch (e) { /* attributes are optional for the scene */ }
  if (!webgl) setup2d();
  buildGround(S.site.layout.pit);
  buildPit(S.site.layout.pit);
  // Second pit (East): same bench geometry, own centre and size.
  for (const [key, q] of Object.entries(S.site.layout.pits || {})) {
    if (key === 'central') continue;
    const { pitMesh } = T3.buildPit(scene, { ...S.site.layout.pit, ...q }, P, VZ);
    pitMesh.userData.twin = `pit-${key}`;
    pickables.push(pitMesh);
    for (let i = 0; i < 6; i++) {
      const th = (i / 6) * Math.PI * 2 + 0.4;
      const m = MD.lightMast(30);
      m.position.copy(P(q.cx + (q.a + 40) * Math.cos(th), q.cy + (q.b + 40) * Math.sin(th), 0));
      scene.add(m); masts.push(m);
    }
  }
  buildRoads(S.site.layout);
  if (DIORAMA) {
    T3.scatterRocks(scene, S.site.layout.pit, P, VZ, S.site.layout, env?.high ? 2600 : 1200);
    for (const [key, q] of Object.entries(S.site.layout.pits || {})) {
      if (key !== 'central') T3.scatterRocks(scene, { ...S.site.layout.pit, ...q }, P, VZ, null, env?.high ? 700 : 350);
    }
  }
  buildShells();
  buildPlant();
  if (webgl) { buildLinks(); fcBuild(); }
  if (env && !env.high) {
    MD.toLambert(scene);
    for (const k of Object.keys(roadMats)) roadMats[k] = MD.lambertOf(roadMats[k]);
  }
  buildTree();
  buildScenarioPanel();
  buildPlanPanel();
  tour = createTour({
    v, num, objs, select, catalog: () => S.catalog, twin: (id) => S.t[id],
    flyTo, follow: (on) => { S.follow = on; $('#followBtn').classList.toggle('active', on); },
    posOf: (id) => (id === 'pit' ? P(0, 150, -120) : objs[id] ? objs[id].position.clone() : null),
  });
  $('#tourBtn').addEventListener('click', () => (tour.running ? tour.stop() : tour.start(0)));
  if (webgl) {
    $('#lyrDay').addEventListener('change', (e) => env.setDayLock(e.target.checked));
    const qs = $('#lyrQuality');
    qs.value = env.quality;
    qs.addEventListener('change', () => env.setQuality(qs.value));
    const st = $('#lyrStyle');
    st.value = env.style;
    st.addEventListener('change', () => env.setStyle(st.value));
  }
  S.ready = true;
  $('#legend').innerHTML = TRUCK_LEGEND.map(([l, k]) => `<span><i style="background:${TRUCK_COLORS[k]}"></i>${l}</span>`).join('') +
    `<span><i style="background:${BLOCK_COLORS.charged}"></i>блок заряжен</span><span><i style="background:${BLOCK_COLORS.mining}"></i>блок в отработке</span>`;
  $('#fcAll').addEventListener('toggle', renderForecast);
  document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === b));
    document.querySelectorAll('.tabbody').forEach((x) => x.classList.toggle('hidden', x.id !== 'tab-' + b.dataset.tab));
  }));
  document.querySelectorAll('.views button').forEach((b) => b.addEventListener('click', () => {
    if (b.dataset.view === 'follow') { S.follow = !S.follow; b.classList.toggle('active', S.follow); if (S.follow && S.selected && objs[S.selected]) { goal.dist = 600 * LENS; } return; }
    setView(b.dataset.view);
  }));
  $('#lnkGrafana').href = `${GRAFANA}/d/bozshakol-overview`;
  $('#aboutBtn').addEventListener('click', () => $('#about').classList.remove('hidden'));
  $('#aboutClose').addEventListener('click', () => $('#about').classList.add('hidden'));
  $('#about').addEventListener('click', (e) => { if (e.target.id === 'about') $('#about').classList.add('hidden'); });
  const q = new URLSearchParams(location.search);
  if (q.get('about')) $('#about').classList.remove('hidden');
  resize();
  setView(q.get('view') || 'overview');
  if (tween) { tween.dur = 1; }
  await poll();
  if (q.get('select')) select(q.get('select'));
  if (q.has('hour')) clock.fixed = +q.get('hour');
  if (q.get('focus')) {
    // Deep link to a close-up: ?focus=sh-02&dist=260&theta=0.8&phi=1.0
    const id = q.get('focus');
    setTimeout(() => {
      const o = objs[id];
      if (!o) return;
      select(id);
      flyTo({ t: o.position.clone(), dist: +(q.get('dist') || 260), theta: +(q.get('theta') || 0.8), phi: +(q.get('phi') || 1.0) }, 600);
      if (o.userData.kind && o.userData.kind !== 'block') setTimeout(() => { S.follow = true; }, 700);
    }, 300);
  }
  if (q.has('tour')) tour.start(+q.get('tour') || 0);
  setInterval(poll, POLL_MS);
}

requestAnimationFrame(frame);
boot();
window.__twin = S;   // for debugging from the browser console
window.__fc3 = fc3;
window.__env = () => ({ env, scene, camera });
window.__objs = objs;   // for debugging from the browser console
window.__setCam = (c) => { tween = null; S.follow = false; goal.target.copy(P(...c.t)); goal.dist = c.dist; goal.theta = c.theta; goal.phi = c.phi; };
