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
              traces: chartDiv.data?.map(trace => trace.name).sort(),
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
    let selected = names.slice();
    await waitSelection(selected);
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
    await page.getByRole('button', {name:'Hide QQQ', exact:true}).click();
    selected = selected.filter(name => name !== 'QQQ');
    frame = await waitSelection(selected);
    await frame.getByRole('checkbox', {name:'Show QQQ on chart', exact:true}).check();
    await waitSelection(names);
    assert.deepEqual(errors, []);
    console.log('PASS: all benchmarks restore; original buttons and panel checkboxes stay synchronized; no page errors.');
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
