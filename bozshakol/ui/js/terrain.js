// Terrain of the Bozshakol site: steppe to the horizon, the Central pit with
// its benches (oxide cap over fresh porphyry), haul roads with gravel and
// safety berms. Model coordinates (x east, y north, z up, metres) map to the
// scene with P() from app.js: (x, z*VZ, -y).
import * as THREE from '../vendor/three/three.module.min.js';
import { steppeTexture, rockTexture, gravelTexture, waterTexture } from './textures.js';

const hash = (x, y) => { const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453; return s - Math.floor(s); };
function vnoise(x, y) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi), b = hash(xi + 1, yi), c = hash(xi, yi + 1), d = hash(xi + 1, yi + 1);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
const fbm = (x, y, o = 5) => { let s = 0, a = 0.5, f = 1, n = 0; for (let i = 0; i < o; i++) { s += a * vnoise(x * f, y * f); n += a; a *= 0.5; f *= 2.03; } return s / n; };

let steppeMat = null;
function groundMaterial() {
  if (steppeMat) return steppeMat;
  const tex = steppeTexture();
  // In the diorama the ground is warm sand, as in a scale model.
  const sand = typeof window !== 'undefined' && document.body.classList.contains('diorama');
  steppeMat = new THREE.MeshStandardMaterial({ color: sand ? '#d9bf98' : '#ffffff', map: tex, vertexColors: true, roughness: 0.97, metalness: 0 });
  return steppeMat;
}

// Ground: one flat grid over the industrial site (with the pit cut out and a
// collar along the rim), and rolling steppe around it up to the horizon.
// Vertex colours darken the ground where it is worked: along haul roads,
// around the plant pads and on the pit rim.
export const SLAB = { X0: -1700, X1: 5400, Y0: -2300, Y1: 2000, depth: 430 };

export function buildGround(scene, pit, VZ, layout = null, coarse = false, slab = false) {
  const mat = groundMaterial();
  const UV = 380;   // metres per texture tile
  const X0 = slab ? SLAB.X0 : -3500, X1 = slab ? SLAB.X1 : 6800, Y0 = slab ? SLAB.Y0 : -3300, Y1 = slab ? SLAB.Y1 : 3300;
  // Disturbance mask from the roads and facilities.
  const segs = [];
  for (const e of layout?.edges || []) for (let i = 1; i < e.pts.length; i++) segs.push([e.pts[i - 1][0], e.pts[i - 1][1], e.pts[i][0], e.pts[i][1]]);
  const facs = Object.values(layout?.facilities || {});
  // All pits of the site (Central at the origin, East offset); older layouts have one.
  const pits = layout?.pits ? Object.values(layout.pits).map((q) => ({ cx: q.cx, cy: q.cy, a: q.a, b: q.b }))
    : [{ cx: 0, cy: 0, a: pit.a, b: pit.b }];
  const inPit = (x, y, pad) => pits.some((q) => ((x - q.cx) / (q.a + pad)) ** 2 + ((y - q.cy) / (q.b + pad)) ** 2 < 1);
  const segDist = (x, y) => {
    let best = 1e9;
    for (const [ax, ay, bx, by] of segs) {
      const dx = bx - ax, dy = by - ay, L = dx * dx + dy * dy || 1;
      const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / L));
      const ex = ax + t * dx - x, ey = ay + t * dy - y;
      const d = ex * ex + ey * ey;
      if (d < best) best = d;
    }
    return Math.sqrt(best);
  };
  const tintAt = (x, y, h = 0) => {
    let k = 0.9 + fbm(x / 1100, y / 1100, 4) * 0.2 + h / 1200;
    let r = 1, g = 1, b = 1;
    // pit rim, roads, facilities: worked ground
    const rim = Math.min(...pits.map((q) => Math.hypot((x - q.cx) / (q.a + 260), (y - q.cy) / (q.b + 260))));
    let dist = rim < 1 ? 1 : Math.max(0, 1 - (rim - 1) * 6);
    if (segs.length && Math.abs(x) < 7000 && Math.abs(y) < 4000) dist = Math.max(dist, Math.max(0, 1 - segDist(x, y) / 90));
    for (const f of facs) dist = Math.max(dist, Math.max(0, 1 - Math.hypot(x - f[0], y - f[1]) / 260) * 0.8);
    dist *= 0.75 + fbm(x / 120, y / 120, 2) * 0.5;
    r = 1 - dist * 0.12; g = 1 - dist * 0.2; b = 1 - dist * 0.26;
    return [k * r, k * g, k * b];
  };
  const makeGrid = (ox0, ox1, oy0, oy1, C, heightFn, skipFn) => {
    const nx = Math.round((ox1 - ox0) / C), ny = Math.round((oy1 - oy0) / C);
    const n = (nx + 1) * (ny + 1);
    const pos = new Float32Array(n * 3), uv = new Float32Array(n * 2), col = new Float32Array(n * 3);
    for (let j = 0; j <= ny; j++) {
      for (let i = 0; i <= nx; i++) {
        const x = ox0 + i * C, y = oy0 + j * C, k = j * (nx + 1) + i;
        const h = heightFn(x, y);
        pos.set([x, h * VZ, -y], k * 3);
        uv.set([x / UV, y / UV], k * 2);
        col.set(tintAt(x, y, h), k * 3);
      }
    }
    const idx = [];
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        if (skipFn(ox0 + (i + 0.5) * C, oy0 + (j + 0.5) * C)) continue;
        const a = j * (nx + 1) + i, b = a + 1, c = a + nx + 1, d = c + 1;
        idx.push(a, b, c, b, d, c);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    g.setIndex(idx);
    g.computeVertexNormals();
    const m = new THREE.Mesh(g, mat);
    m.receiveShadow = true;
    scene.add(m);
    return m;
  };
  // inner site: 50 m grid, cells inside the (rim + 60 m) ellipse are skipped
  const inner = makeGrid(X0, X1, Y0, Y1, coarse ? 100 : 50, () => 0, (x, y) => inPit(x, y, 55));
  // collar: closes the gap between the grid and the exact pit rim
  for (const q of pits) {
    const M = 288, pos = [], uv = [], col = [], idx = [];
    for (let i = 0; i <= M; i++) {
      const th = (i / M) * Math.PI * 2;
      for (const off of [0, 140]) {
        const x = q.cx + (q.a + off) * Math.cos(th), y = q.cy + (q.b + off) * Math.sin(th);
        pos.push(x, 0.15, -y); uv.push(x / UV, y / UV); col.push(...tintAt(x, y));
      }
      if (i < M) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    g.setIndex(idx); g.computeVertexNormals();
    const m = new THREE.Mesh(g, mat); m.receiveShadow = true; scene.add(m);
  }
  if (slab) return { inner, ...buildSlab(scene, VZ, tintAt) };
  // outer steppe: 100 m grid, rises gently away from the site
  const height = (x, y) => {
    const dx = Math.max(X0 - x, 0, x - X1), dy = Math.max(Y0 - y, 0, y - Y1);
    const ramp = THREE.MathUtils.smoothstep(Math.hypot(dx, dy), 0, 2600);
    const hills = fbm(x / 4200, y / 4200, 5) * 140 - 40 + Math.max(0, fbm(x / 9000 + 7, y / 9000) - 0.55) * 900;
    return Math.max(0, hills) * ramp;
  };
  const outer = makeGrid(-16000, 19000, -14000, 14000, coarse ? 250 : 100, height, (x, y) => x > X0 && x < X1 && y > Y0 && y < Y1);
  return { inner, outer };
}

// The pit: alternating steep faces and flat berms, separate vertices so the
// terraces stay crisp; vertex colours go from the red-brown oxide cap to the
// grey-green porphyry; a rock texture adds strata and cracks.
export function buildPit(scene, pit, P, VZ) {
  const cx = pit.cx || 0, cy = pit.cy || 0;
  const dioPit = document.body.classList.contains('diorama');
  const M = (typeof window !== 'undefined' && window.__lowQuality) ? 144 : 288, faceOff = pit.bench_h / Math.tan((65 * Math.PI) / 180);
  const pos = [], col = [], uv = [], idx = [];
  const cOx = new THREE.Color('#a8683c'), cCap = new THREE.Color('#b99c74'), cPorph = new THREE.Color('#7f8a7c'), cDeep = new THREE.Color('#5f6560');
  const cBerm = new THREE.Color('#b8a283');
  // Coincident rings share the same jitter (key = berm level), level 0 (the
  // rim, which meets the ground hole) has none: no cracks between strips.
  const jitter = (th, lvl) => (lvl < 1 ? 1 : 1 + (fbm(Math.cos(th) * 3 + lvl * 3.1, Math.sin(th) * 3 + lvl * 0.7, 3) - 0.5) * 0.007);
  const ring = (a, b, z, isFace, k, vv, lvl, mul = 1) => {
    const start = pos.length / 3;
    for (let i = 0; i <= M; i++) {
      const th = (i / M) * Math.PI * 2;
      const jt = jitter(th, lvl);
      const x = cx + a * jt * Math.cos(th), y = cy + b * jt * Math.sin(th);
      const p = P(x, y, z);
      pos.push(p.x, p.y, p.z);
      const depth = k / pit.n;
      let c = depth < 0.3 ? cCap.clone().lerp(cOx, depth / 0.3) : cOx.clone().lerp(cPorph, Math.min(1, (depth - 0.3) / 0.35)).lerp(cDeep, Math.max(0, depth - 0.65));
      // mineralised zone: greener/greyer patches near the porphyry core
      const ore = Math.max(0, Math.sin(x / 173 + 0.9) * Math.cos(y / 211 - 0.7));
      c.lerp(new THREE.Color('#6f7d70'), ore * 0.35 * depth);
      if (!isFace) c = c.clone().lerp(cBerm, dioPit ? 0.45 : 0.45);
      else if (dioPit) c = c.clone().multiplyScalar(0.82);
      const n = (0.88 + fbm(x / 60, y / 60 + k, 3) * 0.24) * mul;
      col.push(c.r * n, c.g * n, c.b * n);
      const arc = th * (a + b) / 2;
      uv.push(arc / 70, vv);
    }
    return start;
  };
  const strip = (r0, r1) => { for (let i = 0; i < M; i++) idx.push(r0 + i, r1 + i, r0 + i + 1, r0 + i + 1, r1 + i, r1 + i + 1); };
  for (let k = 0; k < pit.n; k++) {
    const a = pit.a - pit.step * k, b = pit.b - pit.step * k;
    const z0 = -pit.bench_h * k, z1 = -pit.bench_h * (k + 1);
    const v0 = (z0 * VZ) / 30, v1 = (z1 * VZ) / 30;
    // Light falls on the crest, the toe of each face sits in its own shadow
    // (baked ambient occlusion): the terraces read at any distance.
    strip(ring(a, b, z0, true, k, v0, k, 1.04), ring(a - faceOff, b - faceOff, z1, true, k + 0.7, v1, k + 1, 0.8));
    strip(ring(a - faceOff, b - faceOff, z1, false, k + 1, v1, k + 1, 0.9), ring(pit.a - pit.step * (k + 1), pit.b - pit.step * (k + 1), z1, false, k + 1, v1 + 0.6, k + 1, 1.0));
  }
  // Drop cut in the floor of a deep pit: the next stage going down (the
  // Lerchs-Grossmann ultimate pit is deeper than today's floor). Visual only,
  // no faces are worked there in the model.
  const aB = pit.a - pit.step * pit.n, bB = pit.b - pit.step * pit.n;
  const drop = pit.n >= 8 ? 2 : 0, dA = aB * 0.5, dB = bB * 0.5;
  for (let j = 0; j < drop; j++) {
    const k = pit.n + j;
    const a = dA - pit.step * j, b = dB - pit.step * j;
    const z0 = -pit.bench_h * k, z1 = -pit.bench_h * (k + 1);
    const v0 = (z0 * VZ) / 30, v1 = (z1 * VZ) / 30;
    strip(ring(a, b, z0, true, k, v0, k, 1.07), ring(a - faceOff, b - faceOff, z1, true, k + 0.7, v1, k + 1, 0.7));
    strip(ring(a - faceOff, b - faceOff, z1, false, k + 1, v1, k + 1, 0.86), ring(a - pit.step, b - pit.step, z1, false, k + 1, v1 + 0.6, k + 1, 1.04));
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  const rock = rockTexture();
  const dio = document.body.classList.contains('diorama');
  // Diorama: smooth painted benches, the strata are carried by vertex colours.
  const pitMat = new THREE.MeshStandardMaterial({ vertexColors: true, map: dio ? null : rock, roughness: 0.95, metalness: 0, side: THREE.DoubleSide });
  const pitMesh = new THREE.Mesh(g, pitMat);
  pitMesh.receiveShadow = true; pitMesh.castShadow = true;
  scene.add(pitMesh);
  // Crest lines: a thin light edge along every bench crest.
  {
    const crest = [];
    for (let k = 1; k < pit.n; k++) {
      const a = pit.a - pit.step * k, b = pit.b - pit.step * k, z = -pit.bench_h * k;
      for (let i = 0; i < M; i++) {
        for (const ii of [i, i + 1]) {
          const th = (ii / M) * Math.PI * 2, jt = jitter(th, k);
          const p = P(cx + a * jt * Math.cos(th), cy + b * jt * Math.sin(th), z);
          crest.push(p.x, p.y + 0.25, p.z);
        }
      }
    }
    const lg = new THREE.BufferGeometry();
    lg.setAttribute('position', new THREE.Float32BufferAttribute(crest, 3));
    scene.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: dioPit ? '#eadbc0' : '#d8c6a4', transparent: true, opacity: dioPit ? 0.22 : 0.2 })));
  }
  // floors: the main floor (a ring around the drop cut) and the drop-cut floor
  const floorTex = rock.clone(); floorTex.repeat.set(10, 6); floorTex.needsUpdate = true;
  const floor = (geo, sx, sy, z) => {
    // mottled: blasted muck, wet patches in vertex colours
    const pp = geo.attributes.position, fc = [];
    const base = new THREE.Color(dioPit ? '#ad9a7f' : '#8a8274');
    for (let i = 0; i < pp.count; i++) {
      const x = pp.getX(i) * sx, y = pp.getY(i) * sy;
      const n = 0.86 + fbm(x / 70 + cx, y / 70 + cy, 3) * 0.28;
      const wet = Math.max(0, fbm(x / 160 + 3, y / 160, 2) - 0.62) * 1.2;
      fc.push(base.r * n * (1 - wet * 0.3), base.g * n * (1 - wet * 0.25), base.b * n * (1 - wet * 0.15));
    }
    geo.setAttribute('color', new THREE.Float32BufferAttribute(fc, 3));
    const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: '#ffffff', vertexColors: true, map: dioPit ? null : floorTex, roughness: 0.95 }));
    m.scale.set(sx, sy, 1); m.rotation.x = -Math.PI / 2;
    m.position.copy(P(cx, cy, z)); m.position.y += 0.1;
    // Diorama: the floor stays readable instead of sinking into the walls' shadow.
    m.receiveShadow = !dioPit;
    scene.add(m);
    return m;
  };
  floor(drop ? new THREE.RingGeometry(0.5, 1, 96, 3) : new THREE.CircleGeometry(1, 96), aB, bB, -pit.bench_h * pit.n);
  const fA = drop ? dA - pit.step * drop : aB, fB = drop ? dB - pit.step * drop : bB, fZ = -pit.bench_h * (pit.n + drop);
  if (drop) floor(new THREE.CircleGeometry(1, 64), fA, fB, fZ);
  // sump with water: smooth, reflects the sky
  const wt = waterTexture();
  const sump = new THREE.Mesh(new THREE.CircleGeometry(1, 48), new THREE.MeshStandardMaterial({ color: dioPit ? '#7fb0bd' : '#5c8494', map: wt, roughness: dioPit ? 0.35 : 0.1, metalness: 0.0, envMapIntensity: 0.6 }));
  sump.scale.set(Math.min(85, fA * 0.3), Math.min(55, fB * 0.3), 1); sump.rotation.x = -Math.PI / 2;
  sump.position.copy(P(cx - fA * 0.4, cy - fB * 0.25, fZ + 0.5));
  scene.add(sump);
  return { pitMesh, sump };
}

// Haul-road ribbon with gravel texture (v along the road) and a low safety
// berm on both shoulders.
let gravel = null;
export function roadGeometry(pts, width, lift, P) {
  const pos = [], uv = [], idx = [];
  let along = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
    let dx = b[0] - a[0], dy = b[1] - a[1];
    const n = Math.hypot(dx, dy) || 1; dx /= n; dy /= n;
    const nx = -dy * width / 2, ny = dx * width / 2;
    if (i > 0) along += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    const l = P(pts[i][0] + nx, pts[i][1] + ny, pts[i][2]), r = P(pts[i][0] - nx, pts[i][1] - ny, pts[i][2]);
    pos.push(l.x, l.y + lift, l.z, r.x, r.y + lift, r.z);
    uv.push(0, along / 30, 1, along / 30);
    if (i < pts.length - 1) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}
// Body of a road that is not at ground level: in the pit a rock shelf one bench
// deep under the road (the bench the road is cut into), on the surface an
// embankment down to the ground with 1:1.5 side slopes. Without it the roads
// and the machines on them would hang over the lower bench or above the steppe.
export function roadBodyGeometry(pts, width, P, benchH) {
  const pos = [], idx = [];
  const side = (sgn) => {
    const start = pos.length / 3;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
      let dx = b[0] - a[0], dy = b[1] - a[1];
      const n = Math.hypot(dx, dy) || 1; dx /= n; dy /= n;
      const z = pts[i][2];
      const bottom = z < -1 ? z - benchH : (z > 0.3 ? 0 : z);
      const h = Math.max(0, z - bottom);
      const off = width / 2, offB = width / 2 + (z > 0.3 ? 1.5 * h : 0.35 * h);
      const t = P(pts[i][0] - dy * off * sgn, pts[i][1] + dx * off * sgn, z);
      const u = P(pts[i][0] - dy * offB * sgn, pts[i][1] + dx * offB * sgn, bottom);
      pos.push(t.x, t.y - 0.05, t.z, u.x, u.y - 0.5, u.z);
      if (i < pts.length - 1) { const k = start + i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
    }
  };
  side(1); side(-1);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

export function bermGeometry(pts, offset, lift, P) {
  // a thin triangular windrow along one shoulder
  const pos = [], idx = [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
    let dx = b[0] - a[0], dy = b[1] - a[1];
    const n = Math.hypot(dx, dy) || 1; dx /= n; dy /= n;
    const nx = -dy, ny = dx;
    const o1 = P(pts[i][0] + nx * (offset - 2.5), pts[i][1] + ny * (offset - 2.5), pts[i][2]);
    const o2 = P(pts[i][0] + nx * offset, pts[i][1] + ny * offset, pts[i][2]);
    const o3 = P(pts[i][0] + nx * (offset + 2.5), pts[i][1] + ny * (offset + 2.5), pts[i][2]);
    pos.push(o1.x, o1.y + lift, o1.z, o2.x, o2.y + lift + 2.4, o2.z, o3.x, o3.y + lift, o3.z);
    if (i < pts.length - 1) { const k = i * 3; idx.push(k, k + 1, k + 3, k + 1, k + 4, k + 3, k + 1, k + 2, k + 4, k + 2, k + 5, k + 4); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}
export function roadMaterial(color) {
  gravel = gravel || gravelTexture();
  return new THREE.MeshStandardMaterial({ color, map: gravel, roughness: 1, metalness: 0, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
}
export const bermMaterial = () => new THREE.MeshStandardMaterial({ color: '#9b8b72', roughness: 1, side: THREE.DoubleSide });

// Irregular terraced heap (waste dump, stockpiles): a lathe of a stepped
// profile with a noisy outline.
export function terracedHeap(radius, height, steps, color, seed = 1) {
  const g = new THREE.CylinderGeometry(1, 1, 1, 64, steps * 2, false);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), y = p.getY(i) + 0.5, z = p.getZ(i);
    const r0 = Math.hypot(x, z);
    if (r0 < 1e-6) { p.setY(i, height); continue; }
    const th = Math.atan2(z, x);
    const step = Math.floor(y * steps * 2) / (steps * 2);
    const frac = 1 - step * 0.55;
    const n = 0.88 + fbm(Math.cos(th) * 2 + seed, Math.sin(th) * 2 + seed, 3) * 0.24;
    p.setXYZ(i, Math.cos(th) * radius * frac * n, y * height, Math.sin(th) * radius * frac * n);
  }
  g.computeVertexNormals();
  const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color, roughness: 0.98, flatShading: true }));
  m.castShadow = true; m.receiveShadow = true;
  return m;
}

let waterTex = null;
export function waterMaterial(color = '#4f7584') {
  waterTex = waterTex || waterTexture();
  return new THREE.MeshStandardMaterial({ color, map: waterTex, roughness: 0.12, metalness: 0.05, envMapIntensity: 0.55 });
}


// ---------------------------------------------------------------- diorama
// The site as a cut-out block of ground: the four sides show the strata
// (steppe soil, loam, red-brown oxide cap, weathered and fresh porphyry,
// bedrock) with wavy boundaries; a thin lip of turf on the top edge.
const STRATA = [
  [0.00, '#c9ab80'], [0.03, '#a9825a'], [0.10, '#9c6a46'], [0.24, '#7f4f36'],
  [0.40, '#6a5244'], [0.58, '#5a5853'], [0.78, '#47494b'], [1.00, '#323438'],
];
function strataColor(t, out) {
  for (let i = 1; i < STRATA.length; i++) {
    if (t <= STRATA[i][0]) {
      // hard-ish band edges: keep most of each band flat, blend near the boundary
      const a = STRATA[i - 1], b = STRATA[i];
      const f = THREE.MathUtils.smoothstep((t - a[0]) / (b[0] - a[0]), 0.78, 1.0);
      return out.set(a[1]).lerp(new THREE.Color(b[1]), f);
    }
  }
  return out.set(STRATA[STRATA.length - 1][1]);
}

export function buildSlab(scene, VZ, tintAt) {
  const { X0, X1, Y0, Y1, depth } = SLAB;
  const D = depth * VZ;
  // outline (counter-clockwise seen from above), sampled every 25 m
  const outline = [];
  const edge = (ax, ay, bx, by) => {
    const n = Math.max(1, Math.round(Math.hypot(bx - ax, by - ay) / 25));
    for (let i = 0; i < n; i++) outline.push([ax + (bx - ax) * i / n, ay + (by - ay) * i / n]);
  };
  edge(X0, Y0, X1, Y0); edge(X1, Y0, X1, Y1); edge(X1, Y1, X0, Y1); edge(X0, Y1, X0, Y0);
  const ROWS = 64;
  const pos = [], col = [], idx = [];
  const c = new THREE.Color();
  const N = outline.length;
  for (let i = 0; i <= N; i++) {
    const [x, y] = outline[i % N];
    const along = (i / N) * 40;
    for (let r = 0; r <= ROWS; r++) {
      const t0 = r / ROWS;
      // wavy strata: the depth coordinate is warped by low-frequency noise
      const warp = (fbm(along * 0.9 + 3, t0 * 4, 3) - 0.5) * 0.09 + Math.sin(along * 0.7) * 0.012;
      const t = THREE.MathUtils.clamp(t0 + warp * (t0 > 0.02 ? 1 : 0), 0, 1);
      strataColor(t, c);
      const grain = 0.86 + fbm(along * 6, t0 * 30, 3) * 0.28;
      // pebbles: sparse darker speckles
      const peb = hash(Math.floor(along * 40), Math.floor(t0 * 120)) > 0.965 ? 0.72 : 1;
      const k = grain * peb * (1 - t0 * 0.18);
      pos.push(x, -t0 * D, -y);
      col.push(c.r * k, c.g * k, c.b * k);
    }
  }
  for (let i = 0; i < N; i++) {
    for (let r = 0; r < ROWS; r++) {
      const a = i * (ROWS + 1) + r, b = a + ROWS + 1;
      idx.push(a, a + 1, b, b, a + 1, b + 1);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  const walls = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.96, metalness: 0, side: THREE.DoubleSide }));
  walls.receiveShadow = true;
  scene.add(walls);
  // bottom
  const bottom = new THREE.Mesh(new THREE.PlaneGeometry(X1 - X0, Y1 - Y0), new THREE.MeshStandardMaterial({ color: '#2f3034', roughness: 1 }));
  bottom.rotation.x = Math.PI / 2; bottom.position.set((X0 + X1) / 2, -D, -(Y0 + Y1) / 2);
  scene.add(bottom);
  // turf lip along the top edge
  const lipPos = [], lipIdx = [], lipCol = [];
  for (let i = 0; i <= N; i++) {
    const [x, y] = outline[i % N];
    const tint = tintAt(x, y);
    lipPos.push(x, 0.4, -y, x, -9 * VZ, -y);
    lipCol.push(0.80 * tint[0], 0.72 * tint[1], 0.52 * tint[2], 0.72, 0.6, 0.42);
    if (i < N) { const k = i * 2; lipIdx.push(k, k + 2, k + 1, k + 1, k + 2, k + 3); }
  }
  const lg = new THREE.BufferGeometry();
  lg.setAttribute('position', new THREE.Float32BufferAttribute(lipPos, 3));
  lg.setAttribute('color', new THREE.Float32BufferAttribute(lipCol, 3));
  lg.setIndex(lipIdx); lg.computeVertexNormals();
  const lip = new THREE.Mesh(lg, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 1, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 }));
  lip.position.set(0, 0, 0); scene.add(lip);
  // the floor under the model: a soft shadow and a fading blueprint grid
  const cx = (X0 + X1) / 2, cz = -(Y0 + Y1) / 2;
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry((X1 - X0) * 1.5, (Y1 - Y0) * 1.7), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { size: { value: new THREE.Vector2((X1 - X0) / 2, (Y1 - Y0) / 2) } },
    vertexShader: 'varying vec2 vP; void main(){ vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: `uniform vec2 size; varying vec2 vP;
      void main(){ vec2 q = abs(vP) - size; float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);
        float a = 0.55 * (1.0 - smoothstep(-200.0, 900.0, d)); gl_FragColor = vec4(0.01, 0.02, 0.05, a); }`,
  }));
  shadow.rotation.x = -Math.PI / 2; shadow.position.set(cx, -D - 18, cz); shadow.renderOrder = -1;
  scene.add(shadow);
  const grid = new THREE.Mesh(new THREE.PlaneGeometry(90000, 90000), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { center: { value: new THREE.Vector2(cx, cz) }, cell: { value: 500.0 } },
    vertexShader: 'varying vec3 vW; void main(){ vec4 w = modelMatrix * vec4(position,1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }',
    fragmentShader: `uniform vec2 center; uniform float cell; varying vec3 vW;
      float lines(vec2 p, float c){ vec2 q = p / c; vec2 g = abs(fract(q - 0.5) - 0.5) / fwidth(q); return 1.0 - min(min(g.x, g.y), 1.0); }
      void main(){
        float r = length(vW.xz - center);
        float fade = 1.0 - smoothstep(3500.0, 26000.0, r);
        float l = lines(vW.xz, cell) * 0.55 + lines(vW.xz, cell * 5.0) * 0.45;
        vec3 col = vec3(0.28, 0.48, 0.78);
        gl_FragColor = vec4(col, l * fade * 0.42);
      }`,
  }));
  grid.rotation.x = -Math.PI / 2; grid.position.set(cx, -D - 20, cz); grid.renderOrder = -2;
  scene.add(grid);
  return { walls, lip, grid };
}


// Scattered boulders and pebbles (diorama detail): instanced low-poly rocks
// on the ground around the pit and along the roads, and on the pit berms.
export function scatterRocks(scene, pit, P, VZ, layout, count = 2600) {
  const geo = new THREE.IcosahedronGeometry(1, 0);
  const mat = new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: 0.9, flatShading: true });
  const mesh = new THREE.InstancedMesh(geo, mat, count);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), sc = new THREE.Vector3(), c = new THREE.Color();
  const palette = ['#6e4a33', '#83593b', '#5b4a3e', '#8d6a4c', '#4a3f38'];
  let n = 0, seed = 1;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const segs = [];
  for (const ed of layout?.edges || []) for (let i = 1; i < ed.pts.length; i++) segs.push([ed.pts[i - 1], ed.pts[i]]);
  for (let tries = 0; n < count && tries < count * 6; tries++) {
    let x, y, z = 0;
    const mode = rnd();
    if (mode < 0.45) {                       // pit benches
      const k = Math.floor(rnd() * pit.n);
      const th = rnd() * Math.PI * 2;
      const a = pit.a - pit.step * (k + 0.5), b = pit.b - pit.step * (k + 0.5);
      x = (pit.cx || 0) + a * Math.cos(th); y = (pit.cy || 0) + b * Math.sin(th); z = -pit.bench_h * (k + 1);
    } else if (mode < 0.8 && segs.length) {  // road shoulders
      const [p0, p1] = segs[Math.floor(rnd() * segs.length)];
      const f = rnd();
      const dx = p1[0] - p0[0], dy = p1[1] - p0[1], L = Math.hypot(dx, dy) || 1;
      const off = (rnd() < 0.5 ? -1 : 1) * (16 + rnd() * 40);
      x = p0[0] + dx * f - dy / L * off; y = p0[1] + dy * f + dx / L * off; z = p0[2] + (p1[2] - p0[2]) * f;
      if (z < -2) continue;                  // in-pit road segments: keep the benches clean
    } else {                                 // around the rim
      const th = rnd() * Math.PI * 2, rr = 1.05 + rnd() * 0.5;
      x = (pit.cx || 0) + (pit.a + 40) * rr * Math.cos(th); y = (pit.cy || 0) + (pit.b + 40) * rr * Math.sin(th);
    }
    const s = 1.5 + rnd() ** 3 * 7;
    e.set(rnd() * 3, rnd() * 3, rnd() * 3); q.setFromEuler(e);
    sc.set(s * (0.8 + rnd() * 0.5), s * (0.5 + rnd() * 0.4), s * (0.8 + rnd() * 0.5));
    const p = P(x, y, z);
    m4.compose(p.setY(p.y + sc.y * 0.4), q, sc);
    mesh.setMatrixAt(n, m4);
    c.set(palette[Math.floor(rnd() * palette.length)]).multiplyScalar(0.85 + rnd() * 0.3);
    mesh.setColorAt(n, c);
    n++;
  }
  mesh.count = n;
  mesh.castShadow = true; mesh.receiveShadow = true;
  scene.add(mesh);
  return mesh;
}
