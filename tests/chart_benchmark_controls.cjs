// Run with: node tests/chart_benchmark_controls.cjs
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || '/repl/tools/bin/chromium',
    args: ['--no-sandbox']
  });
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: 1000}});
    await page.goto(pathToFileURL(path.resolve('components/chart_draw/index.html')).href);
    await page.waitForFunction(() => typeof Plotly !== 'undefined');
    await page.evaluate(() => {
      window.__componentValues = [];
      window.addEventListener('message', event => {
        if (event.data?.type === 'streamlit:setComponentValue')
          window.__componentValues.push({
            value: event.data.value,
            dataType: event.data.dataType
          });
      });
      window.__benchmarkArgs = {
        dates: ['2020-01-01', '2026-01-01'],
        prices: [10, 100],
        qqq_dates: ['2020-01-01', '2026-01-01'],
        qqq_prices: [1, 2],
        qqq_actual: [100, 200],
        tqqq_dates: ['2020-01-01', '2026-01-01'],
        tqqq_prices: [1, 3],
        tqqq_actual: [50, 150],
        selected_benchmarks: ['QQQ', 'TQQQ'],
        chart_height: 900,
        future_end: '2031-01-01',
        lines: []
      };
      window.postMessage({type: 'streamlit:render', args: window.__benchmarkArgs}, '*');
    });
    await page.waitForFunction(() => document.getElementById('chart')._fullLayout);

    const qqq = page.getByRole('checkbox', {name: 'Show QQQ on chart'});
    const tqqq = page.getByRole('checkbox', {name: 'Show TQQQ on chart'});
    assert.equal(await page.locator('#benchmark-toggle-grid input').count(), 8);
    assert.equal(await qqq.isChecked(), true);
    assert.equal(await tqqq.isChecked(), true);

    await tqqq.uncheck();
    await page.waitForFunction(() => window.__componentValues.some(value =>
      value.value.action === 'set_benchmarks' &&
      !value.value.selected_benchmarks.includes('TQQQ') &&
      value.value.selected_benchmarks.includes('QQQ')));
    assert.equal(await page.evaluate(() => window.__componentValues
      .find(value => value.value.action === 'set_benchmarks')?.dataType), 'json');

    await page.evaluate(() => {
      window.__benchmarkArgs.tqqq_dates = [];
      window.__benchmarkArgs.tqqq_prices = [];
      window.__benchmarkArgs.tqqq_actual = [];
      window.__benchmarkArgs.selected_benchmarks = ['QQQ'];
      window.postMessage({type: 'streamlit:render', args: window.__benchmarkArgs}, '*');
    });
    await page.waitForFunction(() => document.getElementById('chart')._fullLayout);
    assert.equal(await qqq.isChecked(), true);
    assert.equal(await tqqq.isChecked(), false);
    assert.equal(await page.evaluate(() =>
      chartDiv.data.some(trace => trace.name === 'TQQQ')), false);

    await tqqq.check();
    await page.waitForFunction(() => window.__componentValues.some(value =>
      value.value.action === 'set_benchmarks' &&
      value.value.selected_benchmarks.includes('TQQQ')));
    console.log('PASS: benchmark panel controls report selections and stay synced after app rerenders.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
