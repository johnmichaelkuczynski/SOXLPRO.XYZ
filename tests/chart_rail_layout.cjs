// Layout regression against the actual component markup; no market/network data.
const { chromium } = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { runEmbeddedRailChecks } = require('./helpers/chart_rail_embedded.cjs');

// Native Tab traversal (including date-input segments), not locator.focus(),
// must scroll the panel itself and keep every focused control inside its viewport.
async function tabTo(page, selector, backwards = false) {
  for (let step = 0; step < 80; step++) {
    await page.keyboard.press(backwards ? 'Shift+Tab' : 'Tab');
    const state = await page.evaluate(selector => {
      const active = document.activeElement;
      const panel = document.getElementById('toolbar');
      const rect = active.getBoundingClientRect();
      const bounds = panel.getBoundingClientRect();
      return {
        reached: active.matches(selector),
        inside: panel.contains(active),
        visible: rect.top >= bounds.top - 1 && rect.bottom <= bounds.bottom + 1
          && rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1,
        name: active.id || active.outerHTML.slice(0, 100),
      };
    }, selector);
    assert.ok(state.inside, `Tab toward ${selector} unexpectedly left the panel: ${state.name}`);
    assert.ok(state.visible, `Tab must reveal ${state.name}`);
    if (state.reached) return;
  }
  assert.fail(`Tab did not reach ${selector}`);
}

async function panelPosition(page) {
  return page.locator('#toolbar').evaluate(el => {
    const rect = el.getBoundingClientRect();
    // Page scrolling is allowed; changing the panel's document position is not.
    return { x: rect.left + scrollX, y: rect.top + scrollY };
  });
}

async function checkKeyboard(page) {
  await page.evaluate(() => {
    resetControlRailSize();
    railManuallySized = true;
    toolbarEl.style.width = '250px';
    toolbarEl.style.height = '180px';
    toolbarEl.scrollTop = 0;
    positionRightControlRail();
  });
  const origin = await panelPosition(page);
  const first = '#rail-handle button:first-child';
  // Focus only seeds the traversal. All subsequent navigation uses real keys.
  await page.locator(first).focus();
  for (const selector of ['#rail-extend-date', '#projection-line', '#selectBtn', '#futureHorizon',
    '#heightSlider', '#widthSlider', '#start-date', '#end-date', '.range-apply']) {
    await tabTo(page, selector);
    if (selector === '#selectBtn') await page.keyboard.press('Enter');
    assert.deepEqual(await panelPosition(page), origin, `${selector}: Tab moved panel`);
  }
  assert.ok(await page.locator('#toolbar').evaluate(el => el.scrollTop > 0));
  await tabTo(page, first, true);
  assert.equal(await page.locator('#toolbar').evaluate(el => el.scrollTop), 0);

  // Seed a valid date, then change its active native segment with the keyboard.
  for (const selector of ['#rail-extend-date', '#start-date', '#end-date']) {
    await tabTo(page, selector);
    await page.locator(selector).fill('2026-10-15');
    await page.keyboard.press('ArrowUp');
    assert.notEqual(await page.locator(selector).inputValue(), '2026-10-15',
      `${selector}: keyboard must edit the date`);
    assert.match(await page.locator(selector).inputValue(), /^\d{4}-\d{2}-\d{2}$/);
    assert.deepEqual(await panelPosition(page), origin, 'Date editing moved panel');
  }
  await tabTo(page, '#futureHorizon', true);
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#futureHorizon').inputValue(), '10');
  assert.equal(await page.evaluate(() => futureHorizonYears), 10);
  assert.deepEqual(await panelPosition(page), origin, 'Select keyboard input moved panel');
  await tabTo(page, '#projection-line', true);
  await page.keyboard.press('Home');
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#projection-line').inputValue(), '');
  assert.deepEqual(await panelPosition(page), origin, 'Projection select moved panel');
  await tabTo(page, '#widthSlider');
  const width = Number(await page.locator('#widthSlider').inputValue());
  await page.keyboard.press('ArrowRight');
  assert.equal(Number(await page.locator('#widthSlider').inputValue()), width + 10);
  assert.deepEqual(await panelPosition(page), origin, 'Slider keyboard input moved panel');

  // A real resize gesture must not steal the current control's focus.
  const handle = await page.locator('.rail-resize-se').boundingBox();
  const panelBeforeResize = await page.locator('#toolbar').boundingBox();
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + 200, handle.y + 120, { steps: 5 });
  await page.mouse.up();
  assert.ok((await page.locator('#toolbar').boundingBox()).width > panelBeforeResize.width,
    'Resize gesture must actually widen the panel');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'widthSlider');
  await page.setViewportSize({ width: 900, height: 650 });
  assert.equal(await page.evaluate(() => document.activeElement.id), 'widthSlider');
  await tabTo(page, '#start-date');

  // Keyboard collapse transfers focus to Show; reopening returns to Collapse
  // so the next Tab continues into the controls rather than restarting the page.
  await tabTo(page, 'button[title="Collapse controls"]', true);
  const beforeCollapse = await panelPosition(page);
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#toolbar').isVisible(), false);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'rail-collapsed-tab');
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#toolbar').isVisible(), true);
  assert.equal(await page.evaluate(() => document.activeElement.title), 'Collapse controls');
  assert.deepEqual(await panelPosition(page), beforeCollapse, 'Collapse/show moved panel');
  await tabTo(page, '#undoBtn');
}

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || '/repl/tools/bin/chromium',
    headless: true, args: ['--no-sandbox'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 720 }, hasTouch: true });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const html = fs.readFileSync('components/chart_draw/index.html', 'utf8')
      .replace(/<script src="[^"]+"><\/script>/g, '');
    await page.setContent(html);
    // This fixture intentionally omits Plotly and market data. Mode/size controls
    // still call relayout; stub only that rendering boundary, not control handlers.
    await page.evaluate(() => {
      window.Plotly = { relayout: () => Promise.resolve() };
    });
    for (const [width, height] of [[250, 180], [400, 300], [520, 400], [250, 720]]) {
      await page.evaluate(([w, h]) => {
        railManuallySized = true;
        toolbarEl.style.width = w + 'px';
        toolbarEl.style.height = h + 'px';
        toolbarEl.scrollTop = 0;
        positionRightControlRail();
      }, [width, height]);
      const metrics = await page.evaluate(() => ({
        transform: getComputedStyle(railContentEl).transform,
        font: parseFloat(getComputedStyle(document.querySelector('.tbtn')).fontSize),
        content: railContentEl.getBoundingClientRect().width,
        panel: toolbarEl.clientWidth,
        scrollable: toolbarEl.scrollHeight > toolbarEl.clientHeight,
        horizontalOverflow: toolbarEl.scrollWidth > toolbarEl.clientWidth,
      }));
      assert.equal(metrics.transform, 'none');
      assert.equal(metrics.font, 14);
      assert.equal(metrics.content, metrics.panel);
      assert.equal(metrics.horizontalOverflow, false);
      assert.equal(metrics.scrollable, true);
      await page.locator('#toolbar').hover();
      await page.mouse.wheel(0, 600);
      await page.waitForTimeout(100);
      assert.ok(await page.locator('#toolbar').evaluate(el => el.scrollTop > 0));
    }
    // Existing reset restores usable dimensions; narrow attempted sizes cannot
    // crush controls below the readable minimum.
    await page.evaluate(() => {
      toolbarEl.style.width = '140px';
      positionRightControlRail();
    });
    assert.ok((await page.locator('#toolbar').boundingBox()).width >= 240);
    await page.evaluate(() => resetControlRailSize());
    assert.equal((await page.locator('#toolbar').boundingBox()).width, 280);
    // Real touch input must scroll a short panel rather than move it.
    await page.evaluate(() => {
      railManuallySized = true;
      toolbarEl.style.height = '300px';
      toolbarEl.scrollTop = 0;
      positionRightControlRail();
    });
    const before = await page.locator('#toolbar').boundingBox();
    const cdp = await page.context().newCDPSession(page);
    const x = before.x + before.width / 2;
    for (let swipe = 0; swipe < 14; swipe++) {
      const start = before.y + before.height - 30;
      await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart',
        touchPoints: [{x, y: start}]});
      for (let i = 1; i <= 10; i++) {
        await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove',
          touchPoints: [{x, y: start - i * 18}]});
        await page.waitForTimeout(15);
      }
      await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    }
    const after = await page.locator('#toolbar').boundingBox();
    assert.equal(after.x, before.x);
    assert.equal(after.y, before.y);
    assert.ok(await page.locator('#toolbar').evaluate(el => el.scrollTop > 500));
    const lower = await page.locator('#widthSlider').boundingBox();
    assert.ok(lower.y >= after.y && lower.y + lower.height <= after.y + after.height,
      'touch swipes must reveal the lower width slider');
    await checkKeyboard(page);
    assert.deepEqual(errors, [], 'Component interactions must not raise browser errors');
    console.log('PASS: readable controls, scrolling, reset, keyboard traversal/editing, resize and collapse focus');
    await runEmbeddedRailChecks();
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
