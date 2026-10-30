// Layout regression against the actual component markup; no market/network data.
const { chromium } = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || '/repl/tools/bin/chromium',
    headless: true, args: ['--no-sandbox'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 720 }, hasTouch: true });
    const html = fs.readFileSync('components/chart_draw/index.html', 'utf8')
      .replace(/<script src="[^"]+"><\/script>/g, '');
    await page.setContent(html);
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
    console.log('PASS: readable controls, full-width layout, scrolling, minimum width, reset');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
