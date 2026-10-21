// Run with: node tests/chart_reset_view.cjs
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || '/repl/tools/bin/chromium',
    args: ['--no-sandbox']
  });
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: 1000}});
    await page.goto(pathToFileURL(path.resolve('components/chart_draw/index.html')).href);
    await page.waitForFunction(() => typeof Plotly !== 'undefined');
    await page.evaluate(() => {
      window.postMessage({type: 'streamlit:render', args: {
        dates: ['2020-01-01', '2026-10-21'], prices: [10, 100],
        vix_dates: ['2020-01-01', '2026-10-21'], vix_prices: [20, 30],
        lines: [{x1: '2020-01-01', x2: '2026-10-21',
          y1: 10, y2: 100, color: '#399349', label: 'Lower Channel Line'}]
      }}, '*');
    });
    await page.waitForFunction(() => document.getElementById('chart')._fullLayout);
    const result = await page.evaluate(async () => {
      const savedLines = JSON.stringify(lines);
      const savedHorizon = futureHorizonYears;
      const savedScale = scaleMode;
      setChartWidth(250);
      setChartHeight(1300);
      setMode('select');
      selectedRange = {start: '2024-01-01', end: '2025-01-01'};
      await Plotly.relayout(chartDiv, {
        'xaxis.range': ['2024-01-01', '2025-01-01'],
        'yaxis.range': [1.5, 1.8],
        shapes: [{type:'rect', x0:'2024-01-01', x1:'2025-01-01', y0:1, y1:2}]
      });
      chartScroll.scrollLeft = 500;
      await resetView();
      const firstRange = JSON.stringify(chartDiv.layout.xaxis.range);
      // Subsequent redraws must not restore the zoom that was just reset.
      renderChart();
      await new Promise(resolve => setTimeout(resolve, 150));
      return {
        linesPreserved: savedLines === JSON.stringify(lines),
        horizonPreserved: savedHorizon === futureHorizonYears,
        scalePreserved: savedScale === scaleMode,
        width: currentChartWidth, height: currentChartHeight,
        sliderWidth: document.getElementById('widthSlider').value,
        sliderHeight: document.getElementById('heightSlider').value,
        scroll: chartScroll.scrollLeft, selection: selectedRange, mode: currentMode,
        shapes: chartDiv.layout.shapes.length,
        xRange: chartDiv.layout.xaxis.range, expectedEnd: getFutureEnd(),
        yRange: chartDiv.layout.yaxis.range, expectedY: yAxisRange(),
        persisted: firstRange === JSON.stringify(chartDiv.layout.xaxis.range),
        hasVix: chartDiv.data.some(trace => trace.name === 'VIX')
      };
    });
    for (const flag of ['linesPreserved', 'horizonPreserved', 'scalePreserved', 'persisted', 'hasVix'])
      assert.equal(result[flag], true, flag);
    assert.equal(result.width, 100);
    assert.equal(result.height, 900);
    assert.equal(result.sliderWidth, '100');
    assert.equal(result.sliderHeight, '900');
    assert.equal(result.scroll, 0);
    assert.equal(result.selection, null);
    assert.equal(result.mode, 'pan');
    assert.equal(result.shapes, 0);
    assert.ok(result.xRange[0].startsWith('2020-01-01'));
    assert.ok(result.xRange[1].startsWith(result.expectedEnd));
    assert.deepEqual(result.yRange, result.expectedY);
    console.log('PASS: Reset View restores axes, size, scrolling and navigation; preserves lines, VIX, scale and horizon across redraw.');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exit(1);});
