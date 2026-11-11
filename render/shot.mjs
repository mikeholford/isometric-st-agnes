// Screenshot a page: node render/shot.mjs <url> <out-prefix> [clickSelector...]
import { chromium } from 'playwright';
const [url, out, ...clicks] = process.argv.slice(2);
const browser = await chromium.launch({ headless: true, args: [`--use-angle=${process.platform === 'darwin' ? 'metal' : 'vulkan'}`, '--ignore-gpu-blocklist'] });
for (const [name, viewport] of [['desktop', { width: 1440, height: 900 }], ['phone', { width: 390, height: 844 }]]) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('requestfailed', (r) => errors.push('failed ' + r.url()));
  page.on('response', (r) => r.status() >= 400 && errors.push(r.status() + ' ' + r.url()));
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${out}-${name}.png` });
  for (const [i, sel] of clicks.entries()) {
    if (name !== 'desktop') break;
    await page.click(sel);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${out}-${name}-click${i}.png` });
  }
  console.log(name, 'errors:', JSON.stringify(errors), 'coords:', await page.textContent('#coords').catch(() => '-'), '|', await page.textContent('#scale').catch(() => '-'));
  await page.close();
}
await browser.close();
