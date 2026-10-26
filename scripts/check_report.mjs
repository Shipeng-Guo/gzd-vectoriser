#!/usr/bin/env node
// Portable offline UI/resource smoke check; this does not assess image fidelity.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const usage = 'Usage: node scripts/check_report.mjs <index.html> --browser /path/to/chrome --out /path/to/qa';
const argv = process.argv.slice(2);
if (argv.includes('--help')) { console.log(usage); process.exit(0); }
const input = argv.shift();
const options = {};
while (argv.length) {
  const key = argv.shift();
  if (!['--browser', '--out'].includes(key) || !argv.length || options[key]) {
    console.error(usage); process.exit(2);
  }
  options[key] = argv.shift();
}
if (!input || input.startsWith('--') || !options['--browser'] || !options['--out']) {
  console.error(usage); process.exit(2);
}

const report = path.resolve(input);
const out = path.resolve(options['--out']);
const result = {
  version: 1, passed: false,
  scope: 'Offline report UI, image decoding and local resources only; no semantic or visual fidelity acceptance.',
  report, viewports: [], errors: [],
};
let browser, page;
const captured = new Set();
let phase = 'setup';
await fs.mkdir(out, { recursive: true });
try {
  const require = createRequire(import.meta.url); // Honors caller-provided NODE_PATH.
  let playwright;
  try { playwright = require('playwright'); }
  catch { playwright = require('playwright-core'); }
  const root = await fs.realpath(path.dirname(report));
  assert((await fs.stat(report)).isFile(), 'Report is not a file');
  browser = await playwright.chromium.launch({ executablePath: path.resolve(options['--browser']), headless: true });
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => result.errors.push(`JavaScript: ${error.message}`));
  // Keep a malformed report offline while recording its attempted requests.
  await page.route(/^https?:/, route => {
    result.errors.push(`External request: ${route.request().url()}`);
    return route.abort();
  });
  const settled = async () => {
    await page.waitForFunction(() => window.reportState && window.reportState.status !== 'loading', undefined, { timeout: 35000 });
    const state = await page.evaluate(() => window.reportState);
    assert.equal(state.status, 'ready', state.errors.join('\n') || 'Report did not become ready');
    assert.equal(state.pending, 0);
  };
  phase = 'initial image decoding';
  await page.goto(pathToFileURL(report).href, { waitUntil: 'domcontentloaded' });
  await settled();
  const initial = await page.evaluate(async () => {
    const ready = await window.reportReady;
    const data = JSON.parse(document.getElementById('report-data').textContent);
    return {
      ready, data,
      images: Array.from(document.images, img => ({ src: img.getAttribute('src'), decoded: img.complete && img.naturalWidth > 0 && img.dataset.decodeState === 'ready', loading: img.loading })),
      links: Array.from(document.querySelectorAll('a[href]'), a => a.getAttribute('href')),
      markersHidden: document.getElementById('markers').hidden,
      initialRanges: ['full', 'local'].map(kind => document.getElementById(kind + '-range').value),
    };
  });
  assert.equal(initial.ready.status, 'ready');
  assert(initial.images.every(img => img.decoded && img.loading === 'eager'), 'An image is not eagerly decoded');
  assert(initial.markersHidden, 'Markers must initially be hidden');
  assert.deepEqual(initial.initialRanges, ['50', '50']);
  const data = initial.data;
  phase = 'local resources';
  const resources = new Set([...initial.links, ...initial.images.map(img => img.src), ...Object.values(data.files), ...data.steps.map(step => step.image).filter(Boolean)]);
  for (const resource of resources) {
    const url = new URL(resource, pathToFileURL(report));
    assert.equal(url.protocol, 'file:', `Resource is not local: ${resource}`);
    const target = await fs.realpath(fileURLToPath(url));
    const relative = path.relative(root, target);
    assert(relative && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative) && relative !== '..', `Resource escapes report directory: ${resource}`);
    assert((await fs.stat(target)).isFile(), `Resource is not a file: ${resource}`);
  }
  result.resources = { local_files: resources.size, visible_and_offscreen_images: initial.images.length, decoded: true };

  for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'narrow', width: 390, height: 844 }]) {
    phase = `${viewport.name} interactions`;
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const kinds = data.regions.length ? ['full', 'local'] : ['full'];
    for (const kind of kinds) {
      const range = page.locator(`#${kind}-range`);
      for (const value of [0, 50, 100]) {
        if (value === 50) await range.evaluate(el => { el.value = '50'; el.dispatchEvent(new Event('input', { bubbles: true })); });
        else { await range.focus(); await range.press(value === 0 ? 'Home' : 'End'); }
        const actual = await page.evaluate(kind => {
          const get = suffix => document.getElementById(kind + '-' + suffix);
          return { value: get('range').value, output: get('value').textContent, clip: get('over').style.clipPath.match(/[-\d.]+/g).map(Number), divider: parseFloat(get('divider').style.left), leftHidden: get('label').hidden, rightHidden: get('compare').querySelector('.tag.right').hidden };
        }, kind);
        assert.deepEqual(actual, { value: String(value), output: `${value}%`, clip: [0, 100 - value, 0, 0], divider: value, leftHidden: value === 0, rightHidden: value === 100 }, `${kind} ${value}% wipe`);
      }
      await range.evaluate(el => { el.value = '50'; el.dispatchEvent(new Event('input', { bubbles: true })); });
    }

    const reference = async (kind, mode) => {
      await page.locator(`#${kind}-${mode}`).click();
      await settled();
      const actual = await page.evaluate(kind => ({ src: document.getElementById(kind + '-reference').getAttribute('src'), source: document.getElementById(kind + '-source').getAttribute('aria-pressed'), before: document.getElementById(kind + '-before').getAttribute('aria-pressed') }), kind);
      assert.deepEqual(actual, { src: mode === 'before' ? data.files.before_render : data.files.source, source: String(mode === 'source'), before: String(mode === 'before') });
    };
    if (data.files.before_render) {
      await reference('full', 'before');
      if (data.regions.length) {
        assert.equal(await page.locator('#local-reference').getAttribute('src'), data.files.source, 'Local reference must be independent');
        await reference('local', 'before');
      }
      await reference('full', 'source');
      if (data.regions.length) {
        assert.equal(await page.locator('#local-reference').getAttribute('src'), data.files.before_render, 'Full reference must be independent');
        await reference('local', 'source');
      }
    } else {
      for (const kind of ['full', 'local']) assert(await page.locator(`#${kind}-before`).isHidden());
    }

    if (data.regions.length) {
      assert(await page.getByLabel('Select review region', { exact: true }).isVisible());
      assert.deepEqual(await page.locator('#region-select option').evaluateAll(options => options.map(option => option.value)), data.regions.map(region => region.id));
      await page.locator('#show-markers').check();
      assert(await page.locator('#markers').isVisible());
      for (let index = 0; index < data.regions.length; index++) {
        const region = data.regions[index];
        // Dispatch marker events directly so intentionally overlapping regions
        // cannot intercept each other's hit target. Native select changes use
        // the browser's change event, and marker clicks must synchronize it.
        for (const method of ['dropdown', 'marker']) {
          if (method === 'dropdown') await page.locator('#region-select').selectOption(region.id);
          else await page.locator('#markers [data-region]').nth(index).dispatchEvent('click');
          const actual = await page.evaluate(() => {
            const values = el => ['left', 'top', 'width', 'height'].map(key => parseFloat(el.style[key]));
            return { selected: Array.from(document.querySelectorAll('[data-region][aria-pressed="true"]'), el => el.dataset.region), title: document.getElementById('local-title').textContent, final: values(document.getElementById('local-final')), reference: values(document.getElementById('local-reference')), marker: values(document.querySelector('#markers [aria-pressed="true"]')) };
          });
          assert.deepEqual(actual.selected, [region.id]);
          assert.equal(await page.locator('#region-select').inputValue(), region.id);
          assert(actual.title.startsWith(region.id + ' / '));
          const [x, y, right, bottom] = region.box_xyxy, w = right - x, h = bottom - y;
          const crop = [-x / w * 100, -y / h * 100, data.canvas.width / w * 100, data.canvas.height / h * 100];
          const marker = [x / data.canvas.width * 100, y / data.canvas.height * 100, w / data.canvas.width * 100, h / data.canvas.height * 100];
          // CSSOM serializes large crop percentages to limited significant digits.
          // Allow only that rounding; real coordinate shifts still fail.
          for (const [actualValues, expected] of [[actual.final, crop], [actual.reference, crop], [actual.marker, marker]]) {
            assert(actualValues.every((value, i) => Math.abs(value - expected[i]) <= Math.max(0.001, Math.abs(expected[i]) * 0.000005)), `Coordinate transform changed for ${region.id}`);
          }
        }
      }
      await page.locator('#region-select').focus();
      // Native popup keystrokes depend on the host window system. Verify focus
      // here; all option changes and linked crops are exercised above.
      assert.equal(await page.evaluate(() => document.activeElement.id), 'region-select');
      await page.locator('#show-markers').uncheck();
      assert(await page.locator('#markers').isHidden());
    } else {
      assert(await page.locator('#region-picker').isHidden());
      assert(await page.locator('#region-select').isDisabled());
      assert(await page.locator('#show-markers').isDisabled());
      assert(await page.locator('#local-card').isHidden());
      assert(await page.locator('#regions-empty').isVisible());
    }
    const layout = await page.evaluate(() => ({ width: document.documentElement.clientWidth, content: document.documentElement.scrollWidth }));
    assert(layout.content <= layout.width + 1, `${viewport.name} has horizontal overflow`);
    await settled();
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path: path.join(out, `${viewport.name}.png`), fullPage: true });
    captured.add(viewport.name);
    result.viewports.push({ name: viewport.name, width: viewport.width, height: viewport.height, range_positions: [0, 50, 100], reference_modes: data.files.before_render ? ['source', 'before'] : ['source'], regions_checked: data.regions.length, passed: true });
  }
  result.passed = result.errors.length === 0;
} catch (error) {
  result.errors.push(`${phase}: ${error.message}`);
} finally {
  // Keep useful diagnostics even when a missing/invalid image prevents the
  // interaction pass. Successful viewport screenshots are not overwritten.
  if (page) for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'narrow', width: 390, height: 844 }]) {
    const screenshot = path.join(out, `${viewport.name}.png`);
    if (captured.has(viewport.name)) continue;
    try {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.screenshot({ path: screenshot, fullPage: true });
    } catch (error) { result.errors.push(`Screenshot ${viewport.name}: ${error.message}`); }
  }
  result.passed = result.passed && result.errors.length === 0;
  if (browser) await browser.close();
  await fs.writeFile(path.join(out, 'check.json'), JSON.stringify(result, null, 2) + '\n');
}
console.log(JSON.stringify({ passed: result.passed, output: out, errors: result.errors }));
process.exitCode = result.passed ? 0 : 1;
