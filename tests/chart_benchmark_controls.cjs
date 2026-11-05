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
    assert.equal(await page.evaluate(() =>
      Object.values(SOXLBenchmarkVisibility.read()).every(visible => visible === false)), true);
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
    await page.evaluate(() => {
      window.__originalPlotSvg = chartDiv.querySelector('.main-svg');
      window.__originalXRange = JSON.stringify(chartDiv.layout.xaxis.range);
      window.__originalYRange = JSON.stringify(chartDiv.layout.yaxis.range);
    });

    await tqqq.uncheck();
    await page.waitForFunction(() =>
      chartDiv.data.find(trace => trace.name === 'TQQQ').visible === 'legendonly');
    assert.equal(await page.evaluate(() => window.__componentValues.length), 0);
    assert.equal(await page.evaluate(() =>
      chartDiv.querySelector('.main-svg') === window.__originalPlotSvg &&
      JSON.stringify(chartDiv.layout.xaxis.range) === window.__originalXRange &&
      JSON.stringify(chartDiv.layout.yaxis.range) === window.__originalYRange), true);

    await page.evaluate(() => {
      // A later, unrelated server update must not undo browser visibility.
      window.postMessage({type: 'streamlit:render', args: window.__benchmarkArgs}, '*');
    });
    await page.waitForFunction(() => document.getElementById('chart')._fullLayout);
    assert.equal(await qqq.isChecked(), true);
    assert.equal(await tqqq.isChecked(), false);
    assert.equal(await page.evaluate(() =>
      chartDiv.data.find(trace => trace.name === 'TQQQ').visible), 'legendonly');

    await tqqq.check();
    await page.waitForFunction(() =>
      chartDiv.data.find(trace => trace.name === 'TQQQ').visible === true);
    assert.equal(await page.evaluate(() => window.__componentValues.length), 0);
    const recovery = await page.evaluate(async () => {
      while (chartRenderTask) await chartRenderTask;
      const originalReact = Plotly.react;
      let active = 0;
      let maximumActive = 0;
      Plotly.react = async function(...args) {
        maximumActive = Math.max(maximumActive, ++active);
        await new Promise(resolve => setTimeout(resolve, 20));
        try { return await originalReact.apply(this, args); }
        finally { active--; }
      };
      for (let i = 0; i < 8; i++) renderChart();
      while (chartRenderTask) await chartRenderTask;
      Plotly.react = () => Promise.reject(new Error('Simulated render failure'));
      await renderChart();
      const errorVisible = !document.getElementById('chart-render-error').hidden;
      Plotly.react = originalReact;
      await renderChart({resetViewport:true});
      return {
        maximumActive, errorVisible,
        recovered: document.getElementById('chart-render-error').hidden &&
          chartDiv.querySelectorAll('.main-svg').length > 0
      };
    });
    assert.equal(recovery.maximumActive, 1);
    assert.equal(recovery.errorVisible, true);
    assert.equal(recovery.recovered, true);
    await page.evaluate(() => {
      window.__frameHeights = [];
      window.addEventListener('message', event => {
        if (event.data?.type === 'streamlit:setFrameHeight')
          window.__frameHeights.push(event.data.height);
      });
    });
    await page.setViewportSize({width:1200, height:5000});
    await page.evaluate(() => {
      for (let i = 0; i < 12; i++) setFrameHeight(document.body.scrollHeight + 20);
    });
    await page.waitForFunction(() => window.__frameHeights.length >= 12);
    const heights = await page.evaluate(() => window.__frameHeights.slice(-12));
    assert.equal(new Set(heights).size, 1, 'Repeated sizing must not grow the iframe');
    assert.ok(heights[0] < 3000, 'Frame size must follow content, not the oversized viewport');
    console.log('PASS: benchmark toggles update the existing SVG and preserve axes without sending server widget events.');
    console.log('PASS: redraws are serialized; rendering errors are visible and retry restores the chart.');
    console.log('PASS: iframe height stays bounded after repeated sizing in an oversized viewport.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
