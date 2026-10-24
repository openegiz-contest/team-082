// Procedural textures for the 3D control room. Everything is drawn on a
// canvas at start-up: no image files, no network, the page stays
// self-contained and works offline in the judge environment.
import * as THREE from '../vendor/three/three.module.min.js';

// Deterministic value noise (seeded), tileable on a period.
function makeNoise(seed = 1) {
  let s = seed >>> 0;
  const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  const P = 256;
  const g = new Float32Array(P * P);
  for (let i = 0; i < g.length; i++) g[i] = rnd();
  const at = (x, y) => g[((y % P + P) % P) * P + ((x % P + P) % P)];
  const smooth = (t) => t * t * (3 - 2 * t);
  const n2 = (x, y, period) => {
    const xi = Math.floor(x), yi = Math.floor(y), xf = smooth(x - xi), yf = smooth(y - yi);
    const w = (v) => ((v % period) + period) % period;
    const a = at(w(xi), w(yi)), b = at(w(xi + 1), w(yi)), c = at(w(xi), w(yi + 1)), d = at(w(xi + 1), w(yi + 1));
    return a + (b - a) * xf + (c - a) * yf + (a - b - c + d) * xf * yf;
  };
  // fractal, tileable over [0, size) when sampled with x,y in pixels
  const fbm = (x, y, size, base = 8, oct = 5) => {
    let amp = 0.5, sum = 0, norm = 0, f = base;
    for (let o = 0; o < oct; o++) {
      sum += amp * n2((x / size) * f, (y / size) * f, f);
      norm += amp; amp *= 0.5; f *= 2;
    }
    return sum / norm;
  };
  return { rnd, n2, fbm };
}

function canvasTex(size, draw, { repeat = 1, srgb = true } = {}) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d');
  draw(ctx, size);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeat, repeat);
  t.anisotropy = 8;
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.needsUpdate = true;
  return t;
}

function fillByNoise(ctx, size, fn) {
  const img = ctx.createImageData(size, size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const [r, g, b] = fn(x, y);
      const i = (y * size + x) * 4;
      img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = b; img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
}

const mix = (a, b, t) => a + (b - a) * t;
const mix3 = (c1, c2, t) => [mix(c1[0], c2[0], t), mix(c1[1], c2[1], t), mix(c1[2], c2[2], t)];

// Autumn steppe of Pavlodar region: straw, olive and dry-earth patches.
export function steppeTexture() {
  const N = makeNoise(7);
  return canvasTex(512, (ctx, s) => {
    fillByNoise(ctx, s, (x, y) => {
      const big = N.fbm(x, y, s, 4, 4);
      const mid = N.fbm(x + 91, y + 37, s, 16, 3);
      const fine = N.rnd();
      let c = mix3([200, 186, 146], [164, 158, 114], Math.min(1, Math.max(0, (big - 0.45) * 2.0)));
      c = mix3(c, [176, 150, 116], Math.max(0, mid - 0.6) * 2.5);
      const k = 0.9 + fine * 0.18;
      return [c[0] * k, c[1] * k, c[2] * k];
    });
    // grass tufts
    for (let i = 0; i < 2600; i++) {
      const x = N.rnd() * s, y = N.rnd() * s;
      ctx.strokeStyle = N.rnd() < 0.4 ? 'rgba(128,118,70,.45)' : 'rgba(222,204,150,.5)';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + (N.rnd() - 0.5) * 3, y - 2 - N.rnd() * 3); ctx.stroke();
    }
  }, { repeat: 1 });
}

// Bench rock: horizontal strata, cracks and blast scars, grey-scale so the
// vertex colours (oxide cap -> fresh porphyry) tint it.
export function rockTexture() {
  const N = makeNoise(13);
  return canvasTex(512, (ctx, s) => {
    fillByNoise(ctx, s, (x, y) => {
      const strata = 0.5 + 0.5 * Math.sin((y / s) * Math.PI * 2 * 9 + N.fbm(x, y, s, 6, 3) * 5);
      const n = N.fbm(x, y, s, 12, 5);
      const v = 196 + (n - 0.5) * 90 + strata * 26 + (N.rnd() - 0.5) * 22;
      return [v, v * 0.98, v * 0.95];
    });
    ctx.strokeStyle = 'rgba(40,36,32,.35)';
    for (let i = 0; i < 160; i++) {
      let x = N.rnd() * s, y = N.rnd() * s;
      ctx.lineWidth = 0.6 + N.rnd() * 1.2;
      ctx.beginPath(); ctx.moveTo(x, y);
      for (let k = 0; k < 5; k++) { x += (N.rnd() - 0.5) * 18; y += 4 + N.rnd() * 14; ctx.lineTo(x, y); }
      ctx.stroke();
    }
  }, { srgb: true });
}

// Haul-road gravel with wheel ruts along the length (texture v = along road).
export function gravelTexture() {
  const N = makeNoise(29);
  return canvasTex(256, (ctx, s) => {
    fillByNoise(ctx, s, (x, y) => {
      const n = N.fbm(x, y, s, 16, 4);
      const rut = Math.exp(-(((x / s) - 0.3) ** 2) / 0.003) + Math.exp(-(((x / s) - 0.7) ** 2) / 0.003);
      const v = 178 + (n - 0.5) * 60 + (N.rnd() - 0.5) * 36 - rut * 30;
      return [v * 1.02, v * 0.96, v * 0.88];
    });
  }, { srgb: true });
}

// Corrugated cladding for plant buildings.
export function claddingTexture(base = [196, 200, 204]) {
  const N = makeNoise(41);
  return canvasTex(256, (ctx, s) => {
    fillByNoise(ctx, s, (x, y) => {
      const rib = 0.82 + 0.18 * Math.abs(Math.sin((x / s) * Math.PI * 32));
      const dirt = N.fbm(x, y, s, 6, 3) * 0.25 + (y / s) * 0.12;
      const k = rib * (1 - dirt * 0.5);
      return [base[0] * k, base[1] * k, base[2] * k];
    });
  });
}

// Windows grid: used both as a colour map (dark glass) and as the emissive
// map that lights up at night.
export function windowsTexture(cols = 8, rows = 3) {
  const N = makeNoise(53);
  return canvasTex(256, (ctx, s) => {
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, s, s);
    const cw = s / cols, rh = s / rows;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const lit = N.rnd() < 0.78;
        ctx.fillStyle = lit ? `rgb(255,${200 + N.rnd() * 40 | 0},${130 + N.rnd() * 60 | 0})` : '#1a1a1a';
        ctx.fillRect(c * cw + cw * 0.18, r * rh + rh * 0.3, cw * 0.64, rh * 0.42);
      }
    }
  });
}

// Soft radial sprite for dust, smoke and light glows.
export function softSprite(inner = 'rgba(255,255,255,1)', outer = 'rgba(255,255,255,0)') {
  return canvasTex(128, (ctx, s) => {
    const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    g.addColorStop(0, inner); g.addColorStop(1, outer);
    ctx.fillStyle = g; ctx.fillRect(0, 0, s, s);
  }, { repeat: 1 });
}

// Water ripples: normal-ish shading baked into colour for ponds.
export function waterTexture() {
  const N = makeNoise(71);
  return canvasTex(256, (ctx, s) => {
    fillByNoise(ctx, s, (x, y) => {
      const n = N.fbm(x, y, s, 10, 4);
      const v = (n - 0.5) * 40;
      return [62 + v, 104 + v, 122 + v];
    });
  });
}
