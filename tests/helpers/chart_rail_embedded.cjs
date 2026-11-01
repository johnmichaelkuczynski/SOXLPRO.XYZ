// Actual Streamlit sandboxed iframe, synthetic prices only; no production app,
// saved-data dependency, probability tests, or session-recovery tests.
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

async function runEmbeddedRailChecks() {
  const port = await freePort();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'rail-layout-'));
  const extension = path.resolve('tests/fixtures/zoom_extension');
  const server = spawn('python', ['-m', 'streamlit', 'run',
    'tests/fixtures/chart_rail_app.py', '--server.address=127.0.0.1',
    `--server.port=${port}`, '--server.headless=true',
    '--browser.gatherUsageStats=false'], { stdio: ['ignore', 'pipe', 'pipe'] });
  let logs = '', context;
  server.stdout.on('data', chunk => { logs += chunk; });
  server.stderr.on('data', chunk => { logs += chunk; });
  try {
    const deadline = Date.now() + 30000;
    while (true) {
      try {
        if ((await fetch(`http://127.0.0.1:${port}/_stcore/health`)).ok) break;
      } catch {}
      if (server.exitCode !== null || Date.now() > deadline) {
        throw Error(`Isolated Streamlit did not start:\n${logs}`);
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    context = await chromium.launchPersistentContext(profile, {
      executablePath: process.env.CHROMIUM_PATH || '/repl/tools/bin/chromium',
      headless: true, viewport: { width: 1200, height: 900 },
      args: ['--no-sandbox', `--disable-extensions-except=${extension}`,
        `--load-extension=${extension}`],
    });
    const worker = context.serviceWorkers()[0] ||
      await context.waitForEvent('serviceworker');
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${port}`);
    const iframe = page.locator('iframe[title$=".chart_rail_layout"]');
    await iframe.waitFor({ timeout: 45000 });
    const frame = await (await iframe.elementHandle()).contentFrame();
    await frame.waitForFunction(() => document.getElementById('chart')._fullLayout,
      null, { timeout: 45000 });
    assert.ok(await iframe.getAttribute('sandbox'), 'use the real Streamlit sandbox');

    // Scroll Streamlit's actual parent scroller, not a fabricated outer page.
    async function placeFrame(top) {
      await iframe.evaluate((el, top) => {
        const scroller = document.querySelector('[data-testid="stMain"]');
        scroller.scrollTop += el.getBoundingClientRect().top - top;
      }, top);
      await page.waitForTimeout(150);
      const actual = (await iframe.boundingBox()).y;
      assert.ok(Math.abs(actual - top) < 2, `parent scroll: ${actual} != ${top}`);
    }

    async function geometry(label) {
      const result = await frame.evaluate(() => {
        const rect = toolbarEl.getBoundingClientRect();
        const fr = window.frameElement.getBoundingClientRect();
        const bounds = visibleRailBounds();
        const handles = [...document.querySelectorAll('.rail-resize-handle')].map(el => {
          const r = el.getBoundingClientRect();
          return { direction: el.dataset.direction,
            x: r.x + r.width / 2, y: r.y + r.height / 2 };
        });
        return { bounds, frameTop: fr.top, frameHeight: innerHeight,
          parentTop: parent.document.querySelector('[data-testid="stHeader"]')?.getBoundingClientRect().bottom || 0,
          parentHeight: parent.innerHeight,
          rect: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
          handles, font: getComputedStyle(document.querySelector('.tbtn')).fontSize,
          transform: getComputedStyle(railContentEl).transform,
          overflow: toolbarEl.scrollWidth > toolbarEl.clientWidth };
      });
      assert.equal(result.bounds.top, Math.max(12, result.parentTop - result.frameTop + 12), label);
      assert.equal(result.bounds.bottom,
        Math.min(result.frameHeight - 12, result.parentHeight - result.frameTop - 12), label);
      assert.equal(result.font, '14px', `${label}: readable text`);
      assert.equal(result.transform, 'none', `${label}: no shrinking content`);
      assert.equal(result.overflow, false, `${label}: no clipped horizontal controls`);
      for (const h of result.handles) {
        const expectedX = /e/.test(h.direction) ? result.rect.right :
          /w/.test(h.direction) ? result.rect.left : (result.rect.left + result.rect.right) / 2;
        const expectedY = /n/.test(h.direction) ? result.rect.top :
          /s/.test(h.direction) ? result.rect.bottom : (result.rect.top + result.rect.bottom) / 2;
        assert.ok(Math.abs(h.x - expectedX) < 1 && Math.abs(h.y - expectedY) < 1,
          `${label}: ${h.direction} resize handle detached`);
      }
      return result;
    }

    async function reachableControls(label) {
      // Wheel the real panel without scrollIntoView: that would silently move
      // the parent and hide precisely the clipping regression being tested.
      await frame.locator('#toolbar').evaluate(el => { el.scrollTop = 0; });
      const seen = new Set();
      let expected;
      for (let step = 0; step < 40; step++) {
        const state = await frame.evaluate(() => {
          const panel = toolbarEl.getBoundingClientRect();
          const fr = window.frameElement.getBoundingClientRect();
          const controls = [...toolbarEl.querySelectorAll('button, input, select')];
          const expected = [], visible = [];
          controls.forEach((el, i) => {
            if (!el.getClientRects().length || el.disabled) return;
            const name = `${i}:${el.id || el.title || el.textContent.trim()}`;
            expected.push(name);
            const r = el.getBoundingClientRect();
            const x = r.x + r.width / 2, y = r.y + r.height / 2;
            if (y > panel.top + 2 && y < panel.bottom - 2 &&
                fr.top + y > 0 && fr.top + y < parent.innerHeight &&
                document.elementFromPoint(x, y)?.closest('button, input, select') === el &&
                parent.document.elementFromPoint(fr.left + x, fr.top + y) === window.frameElement)
              visible.push(name);
          });
          const top = Math.max(panel.top + 12, -fr.top + 65);
          const bottom = Math.min(panel.bottom - 12, parent.innerHeight - fr.top - 12);
          return { expected, visible, x: fr.left + panel.left + panel.width / 2,
            y: fr.top + (top + bottom) / 2, top, bottom,
            scroll: toolbarEl.scrollTop,
            end: toolbarEl.scrollTop + toolbarEl.clientHeight >= toolbarEl.scrollHeight - 1 };
        });
        expected = state.expected;
        state.visible.forEach(name => seen.add(name));
        if (state.end) break;
        assert.ok(state.bottom > state.top, `${label}: panel has a visible wheel target`);
        await page.mouse.move(state.x, state.y);
        await page.mouse.wheel(0, 65);
        await page.waitForTimeout(50);
      }
      assert.ok(expected.length > 20, 'cover the full real toolbar');
      assert.deepEqual(expected.filter(name => !seen.has(name)), [],
        `${label}: controls never reachable by panel scrolling`);
      await frame.locator('#toolbar').evaluate(el => { el.scrollTop = 0; });
    }

    for (const zoom of [1, 1.25, 1.5]) {
      await worker.evaluate(async ({ port, zoom }) => {
        const tabs = await chrome.tabs.query({});
        const tab = tabs.find(tab => tab.url?.startsWith(`http://127.0.0.1:${port}`));
        await chrome.tabs.setZoom(tab.id, zoom);
        if (Math.abs(await chrome.tabs.getZoom(tab.id) - zoom) > .01)
          throw Error('Browser zoom was not applied');
      }, { port, zoom });
      await page.waitForTimeout(200);
      const parentHeight = await page.evaluate(() => innerHeight);
      for (const dock of ['left', 'right']) {
        await frame.evaluate(side => {
          railManuallySized = true;
          toolbarEl.style.height = '180px';
          toolbarEl.style.width = '280px';
          dockControlRail(side);
        }, dock);
        // Only the first 240 CSS px or last 240 CSS px of the iframe visible.
        for (const edge of ['entering', 'leaving']) {
          const height = await frame.evaluate(() => innerHeight);
          await placeFrame(edge === 'entering' ? parentHeight - 240 : 240 - height);
          await geometry(`${zoom}x ${dock} ${edge}`);
          await reachableControls(`${zoom}x ${dock} ${edge}`);
          // Default-size controls must work too, not only a manually shortened
          // panel. Desired size is retained while the visible viewport clips.
          await frame.evaluate(() => {
            railManuallySized = false;
            positionRightControlRail();
          });
          await reachableControls(`${zoom}x ${dock} ${edge} default size`);
          await geometry(`${zoom}x ${dock} ${edge} after panel scrolling`);
          await frame.evaluate(() => {
            railManuallySized = true;
            toolbarEl.style.height = '180px';
            positionRightControlRail();
          });
        }
      }
      // Park through the actual button. Streamlit must consume the new frame
      // height and the parent scroll must bring the parked controls into view.
      await placeFrame(-250);
      await frame.locator('[title="Move controls below chart"]').click();
      await page.waitForTimeout(700);
      assert.equal(await frame.evaluate(() => railDock), 'bottom');
      const parked = await geometry(`${zoom}x parked`);
      assert.ok(Math.abs(parked.frameTop + parked.rect.top - 80) < 3,
        'parking scrolls the real parent to the panel');
      await reachableControls(`${zoom}x parked`);
      const parkedTop = await frame.evaluate(() => railFreeTop);
      await page.mouse.move(20, parentHeight / 2);
      await page.mouse.wheel(0, 60);
      await page.waitForTimeout(150);
      assert.equal(await frame.evaluate(() => railFreeTop), parkedTop,
        'parked controls stay below the chart rather than following the viewport');
      await geometry(`${zoom}x parked after parent scroll`);

      // Exercise a real resize handle, not just its calculated coordinates.
      await placeFrame(80 - parkedTop);
      const handle = frame.locator('[data-direction="se"]');
      const box = await handle.boundingBox();
      const widthBefore = await frame.locator('#toolbar').evaluate(el => el.offsetWidth);
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2 + 35, box.y + box.height / 2 + 20, { steps: 5 });
      await page.mouse.up();
      assert.ok(await frame.locator('#toolbar').evaluate(el => el.offsetWidth) > widthBefore + 25,
        'visible resize handle accepts pointer drag at browser zoom');
      await geometry(`${zoom}x resized`);
      await frame.locator('[title="Dock controls right"]').click();
      assert.equal(await frame.evaluate(() => railDock), 'right');
    }
    assert.deepEqual(errors, [], 'no iframe or parent JavaScript errors');
    console.log('PASS: actual Streamlit iframe, partial visibility, browser zoom, all controls reachable, docking, parking and resize handles');
  } finally {
    if (context) await context.close();
    if (server.exitCode === null) {
      const exited = once(server, 'exit');
      server.kill('SIGTERM');
      const timeout = setTimeout(() => server.kill('SIGKILL'), 5000);
      await exited;
      clearTimeout(timeout);
    }
    fs.rmSync(profile, { recursive: true, force: true });
  }
}

module.exports = { runEmbeddedRailChecks };
