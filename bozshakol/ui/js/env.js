// Atmosphere, lighting and post-processing of the 3D control room.
//
// The sun follows the *model* clock (kz.bozshakol:site / sim_time) for the
// latitude of Bozshakol, so a shift change, dusk and the night shift are seen
// in the scene: at night the plant windows, the truck headlights and the pit
// lighting masts glow. Quality adapts to the GPU: on software rendering
// (llvmpipe, SwiftShader — e.g. a headless VM) shadows and bloom are off.
import * as THREE from '../vendor/three/three.module.min.js';
import { Sky } from '../vendor/three/addons/objects/Sky.js';
import { EffectComposer } from '../vendor/three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from '../vendor/three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from '../vendor/three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from '../vendor/three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from '../vendor/three/addons/postprocessing/OutputPass.js';

const QS = new URLSearchParams(location.search);
const ENV_DAY = +(QS.get('envi') || 0.22);
const HEMI_DAY = +(QS.get('hemi') || 0.3);
const LAT = 51.85 * Math.PI / 180;   // Bozshakol, Pavlodar region
const DECL = -12 * Math.PI / 180;    // late October

// Sun elevation/azimuth (radians) for a local solar hour.
export function sunAngles(hour) {
  const H = (hour - 12) * 15 * Math.PI / 180;
  const sinEl = Math.sin(LAT) * Math.sin(DECL) + Math.cos(LAT) * Math.cos(DECL) * Math.cos(H);
  const el = Math.asin(sinEl);
  const az = Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(LAT) - Math.tan(DECL) * Math.cos(LAT)) + Math.PI;
  return { el, az };
}

const GradeShader = {
  uniforms: { tDiffuse: { value: null }, vignette: { value: 0.32 }, warmth: { value: 0.03 }, night: { value: 0 } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
  fragmentShader: `
    uniform sampler2D tDiffuse; uniform float vignette; uniform float warmth; uniform float night; varying vec2 vUv;
    void main(){
      vec4 c = texture2D(tDiffuse, vUv);
      vec2 d = vUv - 0.5;
      float v = 1.0 - vignette * smoothstep(0.25, 0.85, length(d * vec2(1.25, 1.0)));
      c.rgb *= v;
      c.rgb += vec3(warmth, warmth * 0.4, -warmth * 0.6) * (1.0 - night);
      c.rgb = mix(c.rgb, c.rgb * vec3(0.85, 0.95, 1.18), night * 0.6);
      gl_FragColor = c;
    }`,
};

function detectQuality() {
  const q = QS.get('quality');
  if (q === 'high' || q === 'low') return q;
  try {
    const saved = localStorage.getItem('bozshakol.quality');
    if (saved === 'high' || saved === 'low') return saved;
  } catch (e) { /* storage may be blocked */ }
  try {
    // Probe the GPU on a throw-away context before the real renderer exists,
    // so antialiasing can be decided up front.
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl2') || c.getContext('webgl');
    const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
    const name = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : '';
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
    if (/swiftshader|llvmpipe|software|basic render|softpipe/i.test(name)) return 'low';
  } catch (e) { /* ignore */ }
  return 'high';
}

// Cheap sky for economy mode: a vertical gradient as the scene background.
function gradientSky() {
  const c = document.createElement('canvas'); c.width = 4; c.height = 256;
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  let last = -1;
  return {
    tex,
    paint(night, dusk, over = 0) {
      const key = night + over * 7;
      if (Math.abs(key - last) < 0.03 && last >= 0) return;
      last = key;
      const ctx = c.getContext('2d');
      const top = new THREE.Color('#3f6fa8').lerp(new THREE.Color('#7d868d'), over).lerp(new THREE.Color('#05080f'), night);
      const hor = new THREE.Color('#c7d5e2').lerp(new THREE.Color('#e7b48b'), dusk * 0.6).lerp(new THREE.Color('#1b2534'), night);
      const g = ctx.createLinearGradient(0, 0, 0, 256);
      g.addColorStop(0, '#' + top.getHexString()); g.addColorStop(0.75, '#' + hor.getHexString()); g.addColorStop(1, '#' + hor.getHexString());
      ctx.fillStyle = g; ctx.fillRect(0, 0, 4, 256);
      tex.needsUpdate = true;
    },
  };
}

export function detectStyle() {
  const q = QS.get('style');
  if (q === 'real' || q === 'diorama') return q;
  try {
    const saved = localStorage.getItem('bozshakol.style');
    if (saved === 'real' || saved === 'diorama') return saved;
  } catch (e) { /* storage may be blocked */ }
  return 'diorama';
}

// Diorama backdrop: a deep-navy radial gradient (the "studio" around the model).
function navyBackdrop() {
  const c = document.createElement('canvas'); c.width = 512; c.height = 512;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(256, 210, 20, 256, 256, 380);
  g.addColorStop(0, '#1f3556'); g.addColorStop(0.55, '#14233b'); g.addColorStop(1, '#0a1220');
  ctx.fillStyle = g; ctx.fillRect(0, 0, 512, 512);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function createEnv({ canvas, scene, camera, style = 'diorama' }) {
  const quality = detectQuality();
  const high = quality === 'high';
  const diorama = style === 'diorama';
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: high, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, high ? 1.75 : 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.82;
  renderer.shadowMap.enabled = high;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  // Sky dome (physically based scattering) and a separate scene to bake the
  // image-based lighting from it, so metal and glass reflect the real sky.
  const sky = new Sky();
  sky.scale.setScalar(36000);
  const su = sky.material.uniforms;
  su.turbidity.value = 5.5; su.rayleigh.value = 1.35; su.mieCoefficient.value = 0.0045; su.mieDirectionalG.value = 0.84;
  if (high && !diorama) scene.add(sky);
  const gsky = high || diorama ? null : gradientSky();
  if (gsky) scene.background = gsky.tex;
  if (diorama) scene.background = navyBackdrop();
  const envScene = new THREE.Scene();
  const envSky = new Sky(); envSky.scale.setScalar(1000); envScene.add(envSky);
  const pmrem = new THREE.PMREMGenerator(renderer);
  let envRT = null;

  // Stars for the night shift.
  const starPos = new Float32Array(1800 * 3);
  for (let i = 0; i < 1800; i++) {
    const u = Math.random(), th = Math.random() * Math.PI * 2, ph = Math.acos(1 - u * 0.95);
    starPos.set([Math.sin(ph) * Math.cos(th) * 30000, Math.cos(ph) * 30000, Math.sin(ph) * Math.sin(th) * 30000], i * 3);
  }
  const starGeo = new THREE.BufferGeometry(); starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
  const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: '#dfe8ff', size: 2.2, sizeAttenuation: false, transparent: true, opacity: 0, fog: false, depthWrite: false }));
  if (!diorama) scene.add(stars);

  const hemi = new THREE.HemisphereLight('#dde8f2', '#6b5a44', 0.9);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight('#fff1dc', 3.2);
  sun.castShadow = high;
  sun.shadow.mapSize.set(4096, 4096);
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 1.2;
  sun.shadow.camera.near = 10; sun.shadow.camera.far = 16000;
  scene.add(sun); scene.add(sun.target);
  const moon = new THREE.DirectionalLight('#9fb6ff', 0);
  moon.position.set(2000, 6000, 3000);
  scene.add(moon);

  scene.fog = new THREE.FogExp2('#c9d3dc', diorama ? 0 : 0.000052);
  // Diorama: a cool rim light from behind gives the block and machines a
  // bright edge against the navy backdrop.
  const rim = new THREE.DirectionalLight('#9cc4ff', diorama ? 1.1 : 0);
  rim.position.set(-4000, 2500, -6000);
  scene.add(rim);

  let composer = null, bloom = null, grade = null;
  if (high) {
    const rt = new THREE.WebGLRenderTarget(16, 16, { type: THREE.HalfFloatType, samples: 4 });
    composer = new EffectComposer(renderer, rt);
    composer.addPass(new RenderPass(scene, camera));
    bloom = new UnrealBloomPass(new THREE.Vector2(16, 16), 0.22, 0.55, 0.92);
    if (diorama) bloom.radius = 0.7;
    composer.addPass(bloom);
    grade = new ShaderPass(GradeShader);
    composer.addPass(grade);
    composer.addPass(new OutputPass());
  }

  const state = { hour: 12, night: 0, dayLock: false, lastEnvEl: null, lastEnvAz: null, overcast: 0 };
  const sunDir = new THREE.Vector3();
  const cFogDay = new THREE.Color('#b4c2cf'), cFogDusk = new THREE.Color('#d9a983'), cFogNight = new THREE.Color('#1c2636'), cFogRain = new THREE.Color('#8d969c');
  const cSunDay = new THREE.Color('#fff3e0'), cSunLow = new THREE.Color('#ffb070');

  function setHour(hour) {
    state.hour = state.dayLock ? 11.5 : hour;
    const { el, az } = sunAngles(state.hour);
    // scene axes: x = east, y = up, z = south (-north)
    sunDir.set(Math.cos(el) * Math.sin(az), Math.sin(el), -Math.cos(el) * Math.cos(az)).normalize();
    const elDeg = el * 180 / Math.PI;
    const night = THREE.MathUtils.clamp((2 - elDeg) / 10, 0, 1);         // 0 day .. 1 night
    const dusk = THREE.MathUtils.clamp(1 - Math.abs(elDeg - 3) / 12, 0, 1); // golden hour weight
    state.night = night;
    su.sunPosition.value.copy(sunDir);
    envSky.material.uniforms.sunPosition.value.copy(sunDir);
    for (const k of ['turbidity', 'rayleigh', 'mieCoefficient', 'mieDirectionalG']) envSky.material.uniforms[k].value = su[k].value;
    sun.intensity = THREE.MathUtils.lerp(3.6, 0, night) * THREE.MathUtils.clamp(elDeg / 6, 0.15, 1);
    sun.color.copy(cSunDay).lerp(cSunLow, dusk * 0.8);
    sun.intensity *= 1 - 0.75 * state.overcast;
    moon.intensity = 0.9 * night;
    hemi.intensity = THREE.MathUtils.lerp(HEMI_DAY, 0.75, night);
    hemi.color.set(night > 0.5 ? '#7e93c4' : '#dde8f2');
    hemi.groundColor.set(night > 0.5 ? '#2a2620' : '#6b5a44');
    stars.material.opacity = night * 0.9;
    scene.fog.color.copy(cFogDay).lerp(cFogDusk, dusk * 0.55).lerp(cFogRain, state.overcast * 0.8).lerp(cFogNight, night);
    scene.fog.density = 0.000052 * (1 + state.overcast * 2.2);
    su.turbidity.value = 5.5 + state.overcast * 12; su.rayleigh.value = 1.35 - state.overcast * 0.9;
    renderer.toneMappingExposure = THREE.MathUtils.lerp(0.82, 1.0, night);
    scene.environmentIntensity = THREE.MathUtils.lerp(ENV_DAY, 0.12, night);
    if (bloom) { bloom.strength = THREE.MathUtils.lerp(0.22, 0.85, night); bloom.threshold = THREE.MathUtils.lerp(0.92, 0.55, night); }
    if (grade) grade.uniforms.night.value = night;
    if (gsky) gsky.paint(night, dusk, state.overcast);
    // Re-bake the sky lighting when the sun has moved noticeably.
    if (high && (state.lastEnvEl === null || Math.abs(state.lastEnvEl - elDeg) > 1.5 || Math.abs(state.lastEnvAz - az) > 0.05)) {
      state.lastEnvEl = elDeg; state.lastEnvAz = az;
      const old = envRT;
      envRT = pmrem.fromScene(envScene, 0, 1, 2000);
      scene.environment = envRT.texture;
      if (old) old.dispose();
    }
    if (diorama) {
      // Studio lighting: the sun still follows the model clock, but never
      // drops below ~25° (long soft shadows, no black night), night is a
      // blue-lit miniature with glowing lamps.
      const elD = Math.max(el, 25 * Math.PI / 180);
      sunDir.set(Math.cos(elD) * Math.sin(az), Math.sin(elD), -Math.cos(elD) * Math.cos(az)).normalize();
      sun.intensity = THREE.MathUtils.lerp(2.35, 1.0, night) * (1 - 0.45 * state.overcast);
      sun.color.copy(cSunDay).lerp(cSunLow, dusk * 0.6).lerp(new THREE.Color('#9fb4ff'), night * 0.7);
      hemi.intensity = THREE.MathUtils.lerp(0.5, 0.5, night);
      hemi.color.set('#d6e4ff'); hemi.groundColor.set(night > 0.5 ? '#3a3328' : '#7a6146');
      moon.intensity = 0;
      scene.fog.density = 0;   // no haze over the miniature
      rim.intensity = THREE.MathUtils.lerp(1.1, 1.6, night);
      renderer.toneMappingExposure = THREE.MathUtils.lerp(0.86, 0.85, night);
      scene.environmentIntensity = THREE.MathUtils.lerp(0.09, 0.05, night);
      if (bloom) { bloom.strength = THREE.MathUtils.lerp(0.28, 0.8, night); bloom.threshold = THREE.MathUtils.lerp(0.97, 0.6, night); }
      if (grade) grade.uniforms.night.value = night * 0.5;
      if (!high) { hemi.intensity *= 1.5; }
      return;
    }
    if (!high) { hemi.intensity *= 2.2 - night * 0.6; }
  }

  // The shadow frustum follows the camera target: crisp shadows close up,
  // the whole site when zoomed out.
  function update(target, dist) {
    const half = THREE.MathUtils.clamp(dist * 0.85, 500, 5200);
    const c = sun.shadow.camera;
    if (c.right !== half) { c.left = -half; c.right = half; c.top = half; c.bottom = -half; c.updateProjectionMatrix(); }
    const up = Math.max(0.12, sunDir.y);
    const dir = state.night > 0.95 ? moon.position.clone().normalize() : sunDir.clone().setY(up).normalize();
    sun.target.position.copy(target);
    sun.position.copy(target).addScaledVector(dir, 7000);
    moon.target.position.copy(target);
  }

  function resize(w, h) {
    renderer.setSize(w, h, false);
    if (composer) { composer.setSize(w, h); bloom.resolution.set(w, h); }
  }

  function render() {
    if (composer) composer.render(); else renderer.render(scene, camera);
  }

  // Rain makes the sky overcast (0..1); eased so the change is smooth.
  function setWeather(rainMmH) {
    const target = Math.min(1, rainMmH / 3);
    const prev = state.overcast;
    state.overcast += (target - state.overcast) * 0.02;
    if (Math.abs(prev - state.overcast) > 0.02) state.lastEnvEl = null;
  }

  function setDayLock(on) { state.dayLock = on; state.lastEnvEl = null; setHour(state.hour); }

  function setQuality(q) {
    try { localStorage.setItem('bozshakol.quality', q); } catch (e) { /* ignore */ }
    location.reload();
  }

  function setStyle(st) {
    try { localStorage.setItem('bozshakol.style', st); } catch (e) { /* ignore */ }
    location.reload();
  }

  if (diorama) { sun.shadow.radius = 4; sun.shadow.blurSamples = 12; sun.shadow.normalBias = 0.8; }
  setHour(12);
  return { renderer, sun, hemi, sky, quality, high, style, diorama, setStyle, state, setHour, update, resize, render, setDayLock, setWeather, setQuality, get night() { return state.night; } };
}
