// Run against the running preview: node tests/chart_benchmark_live.cjs
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const names = ['QQQ', 'TQQQ', 'TLT', 'XLU', 'VIX', 'SOX', 'GUSH', 'BTC'];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || '/repl/tools/bin/chromium',
    headless: true, args: ['--no-sandbox']
  });
  let page;
  try {
    page = await browser.newPage({viewport: {width:1440, height:1100}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('https://' + process.env.REPLIT_DEV_DOMAIN + '/',
      {waitUntil:'domcontentloaded', timeout:60000});
    async function findFrame() {
      for (const frame of page.frames()) {
        try {
          if (await frame.locator('#benchmark-toggle-grid input').count() === 8) return frame;
        } catch {}
      }
    }
    async function waitSelection(expected) {
      let last;
      for (let i = 0; i < 120; i++) {
        const frame = await findFrame();
        if (frame) {
          try {
            last = await frame.evaluate(() => ({
              selected: chartData.selected_benchmarks.slice().sort(),
              traces: chartDiv.data?.filter(trace =>
                trace.visible !== 'legendonly' && trace.visible !== false).map(trace => trace.name).sort(),
              svg: chartDiv.querySelectorAll('.main-svg').length,
              error: !document.getElementById('chart-render-error').hidden,
              rendering: Boolean(chartRenderTask),
              width: chartDiv.clientWidth, height: chartDiv.clientHeight
            }));
            if (JSON.stringify(last.selected) === JSON.stringify(expected.slice().sort()) &&
                JSON.stringify(last.traces) === JSON.stringify(['SOXL', ...expected].sort()) &&
                last.svg > 0 && last.width > 0 && last.height > 0 &&
                !last.error && !last.rendering) return frame;
          } catch {}
        }
        await sleep(250);
      }
      throw Error('Selection failed: expected ' + expected + '; got ' + JSON.stringify(last));
    }
    let selected = [];
    let initialFrame = await waitSelection(selected);
    assert.equal(await initialFrame.locator('#benchmark-toggle-grid input:checked').count(), 0);
    console.log('PASS: fresh preview shows only SOXL; all benchmark checkboxes start unchecked.');
    if (process.env.WAIT_FOR_COMPONENT_UPGRADE === '1') {
      const originalUrl = initialFrame.url();
      console.log('READY: existing preview tab is open at ' + originalUrl);
      let upgraded = false;
      for (let i = 0; i < 480; i++) {
        const current = await findFrame();
        if (current && current.url() !== originalUrl &&
            current.url().includes('/component/app.chart_draw_')) {
          upgraded = true;
          break;
        }
        await sleep(250);
      }
      assert.ok(upgraded, 'Already-open preview must receive the new component without browser reload');
      initialFrame = await waitSelection(selected);
      console.log('PASS: existing preview tab received the updated chart without a page reload.');
    }
    await initialFrame.evaluate(() => {
      window.__continuity = {svg:chartDiv.querySelector('.main-svg'), blanks:0, durations:[], running:true};
      document.getElementById('benchmark-toggle-grid').addEventListener('change', () => {
        window.__toggleStart = performance.now();
      }, true);
      chartDiv.on('plotly_restyle', () => {
        if (window.__toggleStart != null) {
          window.__continuity.durations.push(performance.now() - window.__toggleStart);
          window.__toggleStart = null;
        }
      });
      function sample() {
        if (!window.__continuity.running) return;
        if (chartDiv.querySelector('.main-svg') !== window.__continuity.svg ||
            !chartDiv.querySelector('.scatterlayer .js-line')) window.__continuity.blanks++;
        requestAnimationFrame(sample);
      }
      sample();
    });
    for (const name of names) {
      const frame = await waitSelection(selected);
      await frame.getByRole('checkbox', {name:'Show ' + name + ' on chart', exact:true}).check();
      selected.push(name);
      await waitSelection(selected);
    }
    for (const name of names.filter(name => name !== 'TQQQ')) {
      const frame = await waitSelection(selected);
      await frame.getByRole('checkbox', {name:'Show ' + name + ' on chart', exact:true}).uncheck();
      selected = selected.filter(value => value !== name);
      await waitSelection(selected);
    }
    console.log('PASS: TQQQ-only selection retains both TQQQ and SOXL on the rendered graph.');
    let frame = await waitSelection(selected);
    await frame.getByRole('checkbox', {name:'Show TQQQ on chart', exact:true}).uncheck();
    selected = [];
    await waitSelection(selected);
    console.log('PASS: with all benchmarks unchecked, the SOXL graph remains rendered.');
    for (const name of names) {
      frame = await waitSelection(selected);
      await frame.getByRole('checkbox', {name:'Show ' + name + ' on chart', exact:true}).check();
      selected.push(name);
      await waitSelection(selected);
    }
    let buttonsFrame;
    for (const candidate of page.frames()) {
      if (await candidate.locator('#controls button').count() === 8) buttonsFrame = candidate;
    }
    assert.ok(buttonsFrame, 'Original button row is available');
    await buttonsFrame.getByRole('button', {name:'Hide QQQ', exact:true}).click();
    selected = selected.filter(name => name !== 'QQQ');
    frame = await waitSelection(selected);
    await frame.getByRole('checkbox', {name:'Show QQQ on chart', exact:true}).check();
    await waitSelection(names);
    assert.equal(await findFrame(), initialFrame, 'Toggling must not remount the chart iframe');
    const continuity = await initialFrame.evaluate(() => {
      window.__continuity.running = false;
      return {blanks:window.__continuity.blanks, durations:window.__continuity.durations};
    });
    assert.equal(continuity.blanks, 0, 'The SOXL plot must stay visible on every sampled animation frame');
    assert.ok(continuity.durations.length >= 16);
    assert.ok(Math.max(...continuity.durations) < 1000, 'Visibility updates must not wait seconds');
    assert.deepEqual(errors, []);
    console.log('PASS: all benchmarks restore; original buttons and panel checkboxes stay synchronized; no page errors.');
    console.log('PASS: same chart iframe and SVG throughout; zero blank animation frames. Slowest panel toggle: ' +
      Math.round(Math.max(...continuity.durations)) + ' ms.');
  } catch (error) {
    for (const frame of page.frames()) {
      try {
        if (await frame.locator('#benchmark-toggle-grid').count()) {
          console.error('Chart state at failure:', await frame.evaluate(() => ({
            selected:chartData?.selected_benchmarks,
            traces:chartDiv.data?.map(trace=>trace.name),
            checked:[...document.querySelectorAll('#benchmark-toggle-grid input')].map(input=>[input.dataset.symbol,input.checked]),
            svg:chartDiv.querySelectorAll('.main-svg').length,
            error:document.getElementById('chart-render-error').textContent,
            errorVisible:!document.getElementById('chart-render-error').hidden
          })));
        }
      } catch {}
    }
    await page.screenshot({path:'/tmp/chart-selection-failure.png',fullPage:false});
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
