// Headless check for Bolster. The rendered St Agnes tiles are not in this checkout, so this builds a small
// stand-in landscape in the same projection and serves viewer/index.html over it. The giant, the sun, the tide
// and the occlusion are the real viewer code. Open-Meteo is intercepted so the pictures do not depend on the weather.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { chromium } from 'playwright';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const FIX = '/tmp/bolster-fixture';
const OUT = '/opt/cursor/artifacts';
const HX = 110, HZ = 120, RES = 4, SCALE = 6;
const LOOKS = [45, 135, 225, 315];
const CX = 169736.5, CY = 49484.8;

function height(x, z) {
  if (z > 6 && Math.abs(x) < 95 && !(Math.abs(x - 45) < 7 && z < 12)) return 0.42 - (z - 6) * 0.018;
  if (Math.abs(x - 45) < 7 && z <= -18 && z >= -100) {
    const t = (-18 - z) / 76;
    return 8 + 20 * Math.max(0, Math.min(1, t));
  }
  if (z < -92) return 28;
  if (x > -55 && x < -20 && z > -16 && z < 26) return 8;
  const dx = x - 33;
  const dz = z >= -72 && z <= -12 ? 0 : (z < -72 ? z + 72 : z + 12);
  return 8 + 26 * Math.exp(-(dx * dx) / 40 - (dz * dz) / 80);
}

function layout() {
  let minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
  for (const look of LOOKS) {
    const a = look * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    for (const x of [-HX, HX]) for (const z of [-HZ, HZ]) for (const h of [-1, 42]) {
      const u = x * c + z * s;
      const v = (x * s - z * c) / 2 + h * Math.cos(Math.PI / 6);
      minU = Math.min(minU, u); maxU = Math.max(maxU, u);
      minV = Math.min(minV, v); maxV = Math.max(maxV, v);
    }
  }
  const pad = 24;
  const half = Math.max(Math.abs(minU), Math.abs(maxU)) + pad;
  const width = Math.ceil(2 * half * SCALE);
  const top = maxV + pad;
  const heightPx = Math.ceil((top - (minV - pad)) * SCALE);
  return { width, height: heightPx, top };
}

function project(x, z, h, look, map) {
  const a = look * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
  const u = x * c + z * s;
  const v = (x * s - z * c) / 2 + h * Math.cos(Math.PI / 6);
  return [u * SCALE + map.width / 2, (map.top - v) * SCALE];
}

function colorAt(x, z) {
  const h = height(x, z);
  if (h < 0.05) return [58, 118, 164];
  if (h < 2.2) return [214, 196, 156];
  if (Math.abs(x + 40) < 7 && z > -14 && z < 22) return [118, 114, 108];
  if (h > 24) return [118, 92, 62];
  if (h > 16) return [142, 116, 74];
  return [104, 138, 70];
}

function inTri(px, py, a, b, c) {
  const s = (p, q, r) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  const d1 = s(a, b, [px, py]), d2 = s(b, c, [px, py]), d3 = s(c, a, [px, py]);
  return !((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0));
}

function paintGround(map, look) {
  const { width, height: ih } = map;
  const buf = Buffer.alloc(width * ih * 3, 0);
  // A pale sky, so the long shadow has something to fall across.
  for (let i = 0; i < buf.length; i += 3) buf[i] = 186, buf[i + 1] = 206, buf[i + 2] = 214;
  const cols = Math.round((2 * HX) / RES), rows = Math.round((2 * HZ) / RES);
  const cells = [];
  const ang = look * Math.PI / 180;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const x0 = -HX + c * RES, z0 = -HZ + r * RES, x1 = x0 + RES, z1 = z0 + RES;
    const corners = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
    const proj = corners.map(([x, z]) => project(x, z, height(x, z), look, map));
    const depth = corners.reduce((s, [x, z]) => s + (x * Math.sin(ang) - z * Math.cos(ang)), 0);
    cells.push({ proj, depth, rgb: colorAt((x0 + x1) / 2, (z0 + z1) / 2) });
  }
  cells.sort((a, b) => b.depth - a.depth);
  for (const cell of cells) {
    const [a, b, c, d] = cell.proj;
    const minx = Math.max(0, Math.floor(Math.min(a[0], b[0], c[0], d[0])));
    const maxx = Math.min(width - 1, Math.ceil(Math.max(a[0], b[0], c[0], d[0])));
    const miny = Math.max(0, Math.floor(Math.min(a[1], b[1], c[1], d[1])));
    const maxy = Math.min(ih - 1, Math.ceil(Math.max(a[1], b[1], c[1], d[1])));
    for (let y = miny; y <= maxy; y++) for (let x = minx; x <= maxx; x++) {
      if (!inTri(x, y, a, b, c) && !inTri(x, y, a, c, d)) continue;
      const i = (y * width + x) * 3;
      buf[i] = cell.rgb[0]; buf[i + 1] = cell.rgb[1]; buf[i + 2] = cell.rgb[2];
    }
  }
  return buf;
}

function paintObjects(map, look) {
  const { width, height: ih } = map;
  const buf = Buffer.alloc(width * ih * 4, 0);
  const stamp = (x, z, hw, hd, tall, rgb) => {
    const samples = 18;
    for (let iz = 0; iz <= samples; iz++) for (let ix = 0; ix <= samples; ix++) {
      const wx = x - hw + (2 * hw * ix) / samples, wz = z - hd + (2 * hd * iz) / samples;
      const foot = project(wx, wz, 0.2, look, map);
      const top = project(wx, wz, tall, look, map);
      const x0 = Math.max(0, Math.floor(Math.min(foot[0], top[0]) - 1));
      const x1 = Math.min(width - 1, Math.ceil(Math.max(foot[0], top[0]) + 1));
      const y0 = Math.max(0, Math.floor(Math.min(foot[1], top[1])));
      const y1 = Math.min(ih - 1, Math.ceil(Math.max(foot[1], top[1])));
      for (let py = y0; py <= y1; py++) for (let px = x0; px <= x1; px++) {
        const i = (py * width + px) * 4;
        buf[i] = rgb[0]; buf[i + 1] = rgb[1]; buf[i + 2] = rgb[2]; buf[i + 3] = 230;
      }
    }
  };
  // A cottage across the road, low enough that a giant's head clears the roof, and a hedge across the climb.
  stamp(-40, 3, 8, 14, 7.2, [92, 64, 48]);
  stamp(45, -40, 2.4, 10, 2.4, [48, 92, 46]);
  return buf;
}

function encodeWebp(buf, w, h, out, alpha) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(out), { recursive: true });
    const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', alpha ? 'rgba' : 'rgb24', '-s', `${w}x${h}`, '-i', 'pipe:0', '-frames:v', '1', '-c:v', 'libwebp', '-quality', '70', out], { stdio: ['pipe', 'ignore', 'pipe'] });
    let err = '';
    ff.stderr.on('data', (d) => { err += d; });
    ff.on('close', (code) => (code === 0 ? resolve() : reject(new Error(err.slice(-500)))));
    ff.stdin.on('error', () => {});
    ff.stdin.write(buf);
    ff.stdin.end();
  });
}

async function writeDzi(dir, full, width, height, alpha) {
  const maxLevel = Math.ceil(Math.log2(Math.max(width, height)));
  const bpp = alpha ? 4 : 3;
  const jobs = [];
  for (let level = 0; level <= maxLevel; level++) {
    const scale = 2 ** (maxLevel - level);
    const lw = Math.max(1, Math.ceil(width / scale));
    const lh = Math.max(1, Math.ceil(height / scale));
    const levelBuf = Buffer.alloc(lw * lh * bpp);
    for (let y = 0; y < lh; y++) {
      const sy = Math.min(height - 1, (y * scale) | 0);
      for (let x = 0; x < lw; x++) {
        const sx = Math.min(width - 1, (x * scale) | 0);
        const si = (sy * width + sx) * bpp, di = (y * lw + x) * bpp;
        levelBuf[di] = full[si]; levelBuf[di + 1] = full[si + 1]; levelBuf[di + 2] = full[si + 2];
        if (alpha) levelBuf[di + 3] = full[si + 3];
      }
    }
    const cols = Math.ceil(lw / 1024), rows = Math.ceil(lh / 1024);
    for (let row = 0; row < rows; row++) for (let col = 0; col < cols; col++) {
      const tw = Math.min(1024, lw - col * 1024), th = Math.min(1024, lh - row * 1024);
      const tile = Buffer.alloc(tw * th * bpp);
      for (let y = 0; y < th; y++) {
        const src = ((row * 1024 + y) * lw + col * 1024) * bpp;
        levelBuf.copy(tile, y * tw * bpp, src, src + tw * bpp);
      }
      jobs.push(encodeWebp(tile, tw, th, path.join(dir, String(level), `${col}_${row}.webp`), alpha));
    }
  }
  for (let i = 0; i < jobs.length; i += 4) await Promise.all(jobs.slice(i, i + 4));
}

function writeHeight() {
  const cols = Math.round((2 * HX) / RES), rows = Math.round((2 * HZ) / RES);
  const buf = Buffer.alloc(4 + cols * rows * 2);
  buf.writeUInt16LE(cols, 0);
  buf.writeUInt16LE(rows, 2);
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const x = -HX + (c + 0.5) * RES, z = -HZ + (r + 0.5) * RES;
    const v = Math.max(0, Math.min(65535, Math.round((height(x, z) + 100) * 10)));
    buf.writeUInt16LE(v, 4 + (r * cols + c) * 2);
  }
  fs.writeFileSync(path.join(FIX, 'height.bin'), buf);
}

function lane(a, b, p, c, extra = {}) {
  return { a, b, p, c, e: a, ww: 1, w: 0, wb: 0, h: [[], [], [], []], t: [[], [], [], []], ...extra };
}

function writeData(map) {
  const lanes = [
    lane('sandbeach_0', 'sandbeach_1', [[-55, 16], [42, 16]], 'footway'),
    lane('sandbeach_1', 'grass_0', [[42, 16], [45, -18]], 'path'),
    lane('grass_0', 'up_1', [[45, -18], [45, -96]], 'path'),
    lane('up_1', 'top_1', [[45, -96], [-28, -96]], 'path'),
    lane('top_1', 'down_1', [[-28, -96], [-40, -10]], 'path'),
    lane('down_1', 'road_1', [[-40, -10], [-40, 16]], 'residential', { h: [[[4, 22]], [], [], []] }),
    lane('road_1', 'sandbeach_0', [[-40, 16], [-55, 16]], 'footway'),
  ];
  // A hedge along the lower climb, in the view that looks north-east.
  lanes[2].t = [[[12, 34]], [], [], []];
  fs.writeFileSync(path.join(FIX, 'map.json'), JSON.stringify({
    width: map.width, height: map.height, scale: SCALE, top: map.top,
    area: {
      xmin: CX - HX, xmax: CX + HX, ymin: CY - HZ, ymax: CY + HZ, cx: CX, cy: CY, hx: HX, hz: HZ,
      height: { res: RES }, terrain: { res: RES, min: -2, max: 42 },
    },
    views: LOOKS.map((look) => ({
      look,
      tiles: `tiles/${look}_files/`,
      ...(look === 45 ? { objects: 'obj/45_files/' } : {}),
    })),
  }));
  fs.writeFileSync(path.join(FIX, 'traffic.json'), JSON.stringify({ views: LOOKS, lanes, exits: [] }));
  fs.writeFileSync(path.join(FIX, 'places.json'), JSON.stringify([
    { name: 'Chapel Porth', x: CX, y: CY, h: 0 },
    { name: 'St Agnes Beacon', x: 171010, y: 50215.9, h: 0 },
  ]));
  fs.writeFileSync(path.join(FIX, 'roads.json'), '[]');
  fs.writeFileSync(path.join(FIX, 'routes.json'), JSON.stringify({ routes: [], nodes: [] }));
  fs.writeFileSync(path.join(FIX, 'hotspots.json'), JSON.stringify({ spots: [], views: LOOKS, categories: [] }));
}

function serve(map) {
  const types = { '.html': 'text/html', '.json': 'application/json', '.webp': 'image/webp', '.bin': 'application/octet-stream' };
  const server = http.createServer((req, res) => {
    const url = decodeURIComponent(req.url.split('?')[0]);
    const file = url === '/' || url === '/index.html'
      ? path.join(ROOT, 'viewer/index.html')
      : path.join(FIX, url.replace(/^\/+/, ''));
    if (!file.startsWith(FIX) && !file.startsWith(path.join(ROOT, 'viewer'))) {
      res.writeHead(403); res.end(); return;
    }
    fs.readFile(file, (err, data) => {
      if (err) { res.writeHead(404); res.end('missing'); return; }
      res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
      res.end(data);
    });
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port })));
}

function weather(route, { wind, rain, tide }) {
  const url = route.request().url();
  if (url.includes('marine')) {
    const times = [], vals = [];
    for (let h = 0; h < 48; h++) {
      const ms = Date.parse('2026-06-20T00:00:00Z') + h * 3600000;
      times.push(new Date(ms).toISOString().slice(0, 16));
      vals.push(tide);
    }
    return route.fulfill({ json: { hourly: { time: times, sea_level_height_msl: vals } } });
  }
  return route.fulfill({ json: { current: {
    wind_speed_10m: wind, wind_direction_10m: 270, precipitation: rain ? 3 : 0, rain: rain ? 3 : 0, weather_code: rain ? 61 : 1,
  } } });
}

async function openMap(browser, opts) {
  const context = await browser.newContext({
    viewport: opts.viewport || { width: 1280, height: 800 },
    deviceScaleFactor: 1,
    recordVideo: opts.video ? { dir: '/tmp/bolster-video', size: opts.viewport || { width: 1280, height: 800 } } : undefined,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('response', (res) => { if (res.status() >= 400 && !res.url().includes('open-meteo')) errors.push(`${res.status()} ${res.url()}`); });
  await page.route('**/*open-meteo.com/**', (route) => weather(route, opts));
  await page.goto(`http://127.0.0.1:${opts.port}/?view=${opts.view || 45}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => {
    try {
      return viewer && viewer.isOpen() && typeof bolsterPose === 'function' && bolsterPose(Date.now() / 1000);
    } catch (e) {
      window.__openErr = e && e.message;
      return false;
    }
  }, { timeout: 30000 }).catch(async (err) => {
    const why = await page.evaluate(() => window.__openErr || (typeof viewer === 'undefined' ? 'no viewer binding' : (viewer ? 'viewer not open' : 'viewer null'))).catch((e) => e.message);
    console.log('open failed', why, errors.slice(0, 6));
    throw err;
  });
  await page.waitForFunction(() => { try { return bolsterPose(Date.now() / 1000).tideSource === 'open-meteo'; } catch { return false; } }, null, { timeout: 8000 }).catch(() => {});
  await page.evaluate(() => { window.__realNow = Date.now.bind(Date); });
  return { page, context, errors };
}

// Hold Date.now still so the giant keeps one pose, without freezing the tile loader.
async function pinTime(page, ms) {
  await page.evaluate((ms) => {
    window.__bolsterTime = ms;
    Date.now = () => window.__bolsterTime;
  }, ms);
  await page.waitForTimeout(120);
}

// Let the clock run again from the pinned instant, so a recording shows him walking.
async function liveTime(page) {
  await page.evaluate(() => {
    const start = window.__bolsterTime ?? window.__realNow();
    const t0 = performance.now();
    Date.now = () => start + (performance.now() - t0);
  });
}

async function findPose(page, mode) {
  return page.evaluate((mode) => {
    const base = Math.floor(Date.now() / 1000 / 1200) * 1200;
    for (let s = 6; s < 1170; s += 1) {
      const p = bolsterPose(base + s);
      if (!p || p.pause) continue;
      if (mode === 'flat' && p.moving && Math.abs(p.grade) < 0.03 && p.u > 0.3 && p.u < 0.5) return base + s;
      if (mode === 'sand' && p.kind === 'sand' && p.moving && p.u > 0.3 && p.u < 0.55) return base + s;
      if (mode === 'grass' && p.kind === 'grass' && p.moving && p.u > 0.3 && p.u < 0.55 && p.cover < 1) return base + s;
      if (mode === 'hard' && p.kind === 'hard' && p.moving && p.u < 0.07) return base + s;
      if (mode === 'splash' && p.moving && p.u < 0.12 && p.u > 0.02 && Math.abs(p.grade) < 0.08) return base + s;
      if (mode === 'up' && p.grade > 0.18 && p.moving && p.u > 0.3 && p.u < 0.55) return base + s;
      if (mode === 'down' && p.grade < -0.12 && p.moving && p.u > 0.3 && p.u < 0.6) return base + s;
      if (mode === 'occlude' && p.cover > 1.2 && p.cover < 5.2 && p.moving) return base + s;
      if (mode === 'building' && p.underBuilding && p.moving) return base + s;
    }
    return null;
  }, mode);
}

async function show(page, mode, zoom) {
  const t = await findPose(page, mode);
  if (t == null) throw new Error(`no pose for ${mode}`);
  await pinTime(page, t * 1000);
  // Two images make Viewport.imageToViewportCoordinates the wrong conversion. Use the map image.
  const framed = await page.evaluate((z) => {
    setIntro(false, false);
    const g = bolsterNow() || bolsterPose(Date.now() / 1000);
    const item = viewer.world.getItemAt(0);
    const img = groundToImage(g.x, g.z, 1);
    viewer.viewport.zoomTo(item.imageToViewportZoom(z), null, true);
    viewer.viewport.panTo(item.imageToViewportCoordinates(img), true);
    const [px, py] = toPx(g.x, g.z, 2);
    showPoint(px, py);
    const center = item.viewportToImageCoordinates(viewer.viewport.getCenter(true));
    return { x: g.x, z: g.z, px: Math.round(px), py: Math.round(py), cx: Math.round(center.x), cy: Math.round(center.y) };
  }, zoom);
  const inside = Math.hypot(framed.px - framed.cx, framed.py - framed.cy) < 90;
  if (!inside) console.log('off screen', mode, JSON.stringify(framed));
  await page.waitForFunction(() => {
    const c = viewer.drawer.canvas;
    const d = c.getContext('2d').getImageData(c.width >> 1, c.height >> 1, 1, 1).data;
    return d[0] + d[1] + d[2] > 80;
  }, null, { timeout: 6000 }).catch(() => {});
  await page.waitForTimeout(200);
  return t;
}

async function shot(page, name) {
  fs.mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, name);
  await page.screenshot({ path: file });
  return file;
}

const checks = [];
function check(ok, name, detail) {
  checks.push({ ok: !!ok, name, detail });
  console.log(`${ok ? 'ok' : 'FAIL'}  ${name}${detail != null ? `  ${detail}` : ''}`);
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const map = layout();
  if (process.env.REUSE === '1' && fs.existsSync(path.join(FIX, 'map.json'))) {
    console.log('reusing ground tiles', map);
    writeData(map);
    console.log('objects');
    await writeDzi(path.join(FIX, 'obj', '45_files'), paintObjects(map, 45), map.width, map.height, true);
  } else {
    fs.rmSync(FIX, { recursive: true, force: true });
    fs.mkdirSync(FIX, { recursive: true });
    console.log('map', map);
    writeHeight();
    writeData(map);
    for (const look of LOOKS) {
      console.log('tiles', look);
      await writeDzi(path.join(FIX, 'tiles', `${look}_files`), paintGround(map, look), map.width, map.height, false);
    }
    console.log('objects');
    await writeDzi(path.join(FIX, 'obj', '45_files'), paintObjects(map, 45), map.width, map.height, true);
  }
  const { server, port } = await serve(map);
  console.log('serving', port);
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const dry = { port, wind: 2, rain: false, tide: -1.2, view: 45 };
    const { page, errors } = await openMap(browser, { ...dry, time: '2026-06-21T12:21:00Z' });
    await pinTime(page, Date.parse('2026-06-21T12:21:00Z'));
    const physics = await page.evaluate(() => {
      const base = Math.floor(Date.now() / 1000 / 1200) * 1200;
      let flat = null, up = null, down = null, sand = null;
      for (let s = 6; s < 1170; s++) {
        const p = bolsterPose(base + s);
        if (!p || p.pause) continue;
        if (!flat && Math.abs(p.grade) < 0.03 && p.moving && p.u > 0.32 && p.u < 0.48) flat = p;
        if (!up && p.grade > 0.18 && p.moving) up = p;
        if (!down && p.grade < -0.12 && p.moving) down = p;
        if (!sand && p.kind === 'sand') sand = p;
      }
      const planted = flat && bolsterPose(base + flat.since);
      const later = flat && bolsterPose(base + flat.since + 0.15);
      const noon = bolsterPose(Date.parse('2026-06-21T12:21:00Z') / 1000).sun;
      const dusk = bolsterPose(Date.parse('2026-06-21T20:15:00Z') / 1000).sun;
      const night = bolsterPose(Date.parse('2026-06-21T23:30:00Z') / 1000).sun;
      const shadow = (sun) => (sun.up > 0 ? Math.hypot(sun.x, sun.z) / Math.max(0.08, sun.up) : 0);
      setLook(0);
      let hidden = null, clear = null;
      for (let s = 6; s < 1170 && !hidden; s++) {
        const p = bolsterPose(base + s);
        if (p && p.cover > 1.2 && p.cover < 5.2) hidden = p;
      }
      const at = hidden ? base + hidden.since : base + 100;
      setLook(2);
      clear = bolsterPose(at);
      setLook(0);
      return {
        stepT: flat && flat.stepT, swingT: flat && flat.swingT, leg: flat && flat.leg,
        flatSpeed: flat && flat.speed, flatSl: flat && flat.sl,
        stanceSame: flat && later && Math.hypot(flat.stance.x - later.stance.x, flat.stance.z - later.stance.z),
        swingMoved: flat && later && Math.hypot(flat.swing.x - later.swing.x, flat.swing.z - later.swing.z),
        up: up && { speed: up.speed, sl: up.sl, lean: up.lean, grade: up.grade },
        down: down && { speed: down.speed, lean: down.lean, grade: down.grade },
        noon, dusk, night, shadowNoon: shadow(noon), shadowDusk: shadow(dusk),
        tide: planted && planted.tide, tideSource: planted && planted.tideSource, wind: planted && planted.wind,
        cover45: hidden && hidden.cover, cover225: clear && clear.cover,
        building: !!bolsterPose(base + (hidden ? hidden.since : 10)),
      };
    });
    console.log(JSON.stringify(physics, null, 2));
    const expectStep = Math.PI * Math.sqrt(physics.leg / 9.81);
    check(physics.stepT > 1.6 && physics.stepT < 2.2, 'step is about two seconds', physics.stepT?.toFixed(3));
    check(Math.abs(physics.stepT - expectStep) < 1e-9, 'step is half a pendulum period', `${physics.stepT} vs ${expectStep}`);
    check(Math.abs(physics.swingT - 2 * physics.stepT) < 1e-9, 'full swing is 2π√(L/g)');
    check(physics.stanceSame < 0.001, 'stance foot stays planted', physics.stanceSame);
    check(physics.swingMoved > 0.02, 'swing foot moves', physics.swingMoved);
    check(physics.flatSpeed > 1.75 && physics.flatSpeed < 1.95, 'flat pace is 1.9 m/s', physics.flatSpeed);
    check(physics.up && physics.up.speed < physics.flatSpeed - 0.2 && physics.up.sl < physics.flatSl - 0.4 && physics.up.lean > 0.05, 'uphill is shorter, slower, leaning in', JSON.stringify(physics.up));
    check(physics.down && physics.down.speed < 1.9 && physics.down.lean < -0.02, 'downhill brakes and leans back', JSON.stringify(physics.down));
    check(physics.noon.up > 0.8 && Math.abs(physics.noon.az - Math.PI) < 0.15, 'midsummer noon sun is high and south', `alt ${(physics.noon.alt * 180 / Math.PI).toFixed(1)} az ${(physics.noon.az * 180 / Math.PI).toFixed(1)}`);
    check(physics.dusk.up > 0 && physics.dusk.up < 0.08 && physics.shadowDusk > physics.shadowNoon * 8, 'dusk shadow is much longer', `${physics.shadowDusk.toFixed(1)} vs ${physics.shadowNoon.toFixed(1)}`);
    check(physics.night.up < 0, 'night has no sun', physics.night.up);
    check(physics.tideSource === 'open-meteo' && physics.tide < -1, 'tide forecast is used', `${physics.tideSource} ${physics.tide}`);
    check(physics.cover45 > 1.2 && physics.cover45 < 5.2 && physics.cover225 < 0.6, 'the ridge hides him in one view and not the opposite', `${physics.cover45} / ${physics.cover225}`);

    await show(page, 'flat', 4.2);
    await shot(page, 'bolster-day-walk.png');
    await show(page, 'up', 3.6);
    await shot(page, 'bolster-day-uphill.png');
    await show(page, 'down', 3.6);
    await shot(page, 'bolster-day-downhill.png');
    await show(page, 'sand', 4.5);
    await shot(page, 'bolster-sand-prints.png');
    await show(page, 'grass', 4.2);
    await shot(page, 'bolster-grass-prints.png');
    await show(page, 'hard', 5);
    await shot(page, 'bolster-tarmac-dust.png');
    await show(page, 'sand', 2.2);
    await shot(page, 'bolster-gulls-day.png');
    await show(page, 'occlude', 3.2);
    await shot(page, 'bolster-occlusion-day.png');
    await show(page, 'building', 4);
    await shot(page, 'bolster-building-day.png');

    const rumour = await page.evaluate(() => {
      setIntro(true, false);
      paintRumour();
      return document.getElementById('bolster-rumour').textContent;
    });
    check(rumour && !/—/.test(rumour) && /Bolster|rumour|tall figure|walks again/i.test(rumour), 'rumour is plain prose', rumour);
    await shot(page, 'bolster-rumour.png');

    await pinTime(page, Date.parse('2026-06-21T20:15:00Z'));
    await show(page, 'flat', 1.6);
    await shot(page, 'bolster-dusk-shadow.png');
    await show(page, 'up', 2.4);
    await shot(page, 'bolster-dusk-uphill.png');

    await pinTime(page, Date.parse('2026-06-21T23:30:00Z'));
    await show(page, 'flat', 2.2);
    await shot(page, 'bolster-night-lantern.png');
    await show(page, 'sand', 2.4);
    await shot(page, 'bolster-night-sand.png');

    // The card, after the pictures of him walking, so the earlier shots still have him on the map.
    // Forty seconds into the leg is inside the first two minutes, so this is the setting-out card.
    const legStart = await page.evaluate(() => Math.floor(Date.now() / 1000 / 1200) * 1200 + 40);
    await pinTime(page, legStart * 1000);
    await page.evaluate(() => {
      setIntro(false, false);
      const g = bolsterNow();
      const item = viewer.world.getItemAt(0);
      const img = groundToImage(g.x, g.z, 1);
      viewer.viewport.zoomTo(item.imageToViewportZoom(2.2), null, true);
      viewer.viewport.panTo(item.imageToViewportCoordinates(img), true);
    });
    await page.waitForTimeout(300);
    const found = await page.evaluate(() => {
      const g = bolsterNow();
      const before = g && g.since;
      foundBolster();
      return {
        before,
        title: document.getElementById('bolster-title').textContent,
        lore: document.getElementById('bolster-lore').textContent,
        src: document.getElementById('bolster-src').textContent,
        count: document.getElementById('bolster-count').textContent,
        share: bolsterNote(),
        hidden: document.getElementById('bolster').hidden,
      };
    });
    check(found.before < 120 && found.title === 'You found him as he set out', 'the first two minutes get the setting-out card', `${found.before} ${found.title}`);
    check(/Hunt|1742|1398/.test(found.src), 'lore names its source', found.src);
    check(/#bolster=\d+/.test(found.share) && /same place/.test(found.share), 'share note carries the link', found.share.split('\n')[0]);
    check(/Your finds: 1/.test(found.count), 'the tally starts at one', found.count);
    check(!found.hidden, 'the card is open');
    await shot(page, 'bolster-find-card.png');
    await page.evaluate(() => closeBolster());

    console.log('page errors', errors.filter((e) => !/favicon/.test(e)).slice(0, 12));
    check(!errors.some((e) => /is not a function|is not defined|Cannot read/.test(e)), 'the page drew without a script error', errors[0] || '');
    await page.context().close();

    // High tide and rain, still the real viewer.
    const wet = await openMap(browser, { port, wind: 11, rain: true, tide: 0.85, view: 45 });
    await pinTime(wet.page, Date.parse('2026-06-21T12:21:00Z'));
    const wetness = await wet.page.evaluate(() => {
      const p = bolsterPose(Date.now() / 1000);
      return { wet: p.wet, wind: p.wind, tide: p.tide, rain: p.wet > 0 };
    });
    check(wetness.wet > 0.5 && wetness.wind > 8, 'rain and wind arrive from the forecast', JSON.stringify(wetness));
    check(wetness.tide > 0.7, 'a high tide is in force', wetness.tide);
    await show(wet.page, 'sand', 3.2);
    await shot(wet.page, 'bolster-tide-and-rain.png');
    await show(wet.page, 'splash', 3.6);
    await shot(wet.page, 'bolster-rain-day.png');
    await pinTime(wet.page, Date.parse('2026-06-21T23:30:00Z'));
    await show(wet.page, 'sand', 2.6);
    await shot(wet.page, 'bolster-night-wade.png');
    check(!wet.errors.some((e) => /is not a function|is not defined|Cannot read/.test(e)), 'rain page drew cleanly', wet.errors[0] || '');
    await wet.context.close();

    // The opposite view: the ridge is behind him, so he stands clear of it.
    const back = await openMap(browser, { port, wind: 2, rain: false, tide: -1.2, view: 225 });
    await pinTime(back.page, Date.parse('2026-06-21T12:21:00Z'));
    const clear = await back.page.evaluate(() => {
      const base = Math.floor(Date.now() / 1000 / 1200) * 1200;
      for (let s = 6; s < 1170; s++) {
        const p = bolsterPose(base + s);
        if (p && p.grade > 0.15 && p.moving) return { cover: p.cover, underBuilding: p.underBuilding };
      }
      return null;
    });
    check(clear && clear.cover < 0.8, 'looking the other way, the ridge does not cover him', JSON.stringify(clear));
    await show(back.page, 'up', 3.2);
    await shot(back.page, 'bolster-occlusion-clear.png');
    await pinTime(back.page, Date.parse('2026-06-21T20:15:00Z'));
    await show(back.page, 'flat', 2);
    await shot(back.page, 'bolster-dusk-clear.png');
    await pinTime(back.page, Date.parse('2026-06-21T23:30:00Z'));
    await show(back.page, 'flat', 2.2);
    await shot(back.page, 'bolster-night-clear.png');
    await back.context.close();

    // A phone-sized window, one frame of the walk.
    const phone = await openMap(browser, { port, wind: 2, rain: false, tide: -1.2, view: 45, viewport: { width: 390, height: 844 } });
    await pinTime(phone.page, Date.parse('2026-06-21T12:21:00Z'));
    await show(phone.page, 'flat', 2.8);
    await shot(phone.page, 'bolster-mobile-day.png');
    await pinTime(phone.page, Date.parse('2026-06-21T23:30:00Z'));
    await show(phone.page, 'flat', 2.2);
    await shot(phone.page, 'bolster-mobile-night.png');
    check(!phone.errors.some((e) => /is not a function|is not defined|Cannot read/.test(e)), 'a phone-sized view still draws', phone.errors[0] || '');
    await phone.context.close();

    // A few seconds of him walking, stitched with the system ffmpeg. Playwright's own ffmpeg is not installed here.
    const frames = '/tmp/bolster-frames';
    fs.rmSync(frames, { recursive: true, force: true });
    fs.mkdirSync(frames);
    const vid = await openMap(browser, { port, wind: 4, rain: false, tide: -1.2, view: 45 });
    await pinTime(vid.page, Date.parse('2026-06-21T12:21:00Z'));
    await show(vid.page, 'flat', 3.2);
    await liveTime(vid.page);
    for (let i = 0; i < 28; i++) {
      await new Promise((r) => setTimeout(r, 160));
      await vid.page.screenshot({ path: path.join(frames, `f${String(i).padStart(2, '0')}.png`) });
    }
    await vid.context.close();
    await new Promise((resolve, reject) => {
      const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', '8', '-i', path.join(frames, 'f%02d.png'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', path.join(OUT, 'bolster-walk.mp4')], { stdio: 'inherit' });
      ff.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg ${code}`))));
    });
  } finally {
    await browser.close();
    server.close();
  }
  const failed = checks.filter((c) => !c.ok);
  fs.writeFileSync(path.join(OUT, 'bolster-checks.json'), JSON.stringify(checks, null, 2));
  if (failed.length) {
    console.error(`${failed.length} checks failed`);
    process.exit(1);
  }
  console.log(`${checks.length} checks passed`);
}

main().catch((err) => { console.error(err); process.exit(1); });
