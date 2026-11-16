const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const axis = require('../components/chart_draw/price_axis.js');
const html = fs.readFileSync('components/chart_draw/index.html', 'utf8');
const history = ['2020-01-01', '2026-11-16'];
const future = ['2070-01-01', '2080-01-01'];
const fullLayout = {xaxis: {range: future}, yaxis: {range: [5, 8]}};
const context = {
  chartDiv: {
    layout: {xaxis: {range: history}, yaxis: {range: [-1, 3]}},
    _fullLayout: fullLayout
  },
  chartScroll: {scrollLeft: 0, scrollTop: 0}
};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('function captureChartViewport()'),
  html.indexOf('\nfunction renderChart(options)')), context);
assert.equal(JSON.stringify(context.captureChartViewport().xRange), JSON.stringify(future),
  'Projection redraws must capture the displayed future range, not stale Plotly input');
assert.equal(JSON.stringify(context.captureChartViewport().yRange), '[5,8]');

let active = true, updates = 0, navigations = 0;
const handlers = {};
const chart = {
  data: [{x: history, y: [1, 50]}],
  layout: {xaxis: {range: history.slice()}, yaxis: {range: [-1, 3]}},
  _fullLayout: {
    xaxis: {range: future.slice()},
    yaxis: {range: [5, 8], _length: 562}
  },
  on: (name, handler) => { handlers[name] = handler; }
};
global.Plotly = {relayout: async (_, update) => {
  assert.ok(++updates < 5, 'Range synchronization must converge');
  Object.entries(update).forEach(([key, value]) => {
    const [name, property] = key.split('.');
    chart.layout[name][property] = value;
  });
  // A label redraw consumes the input layout; stale ranges here reproduce snap-back.
  chart._fullLayout.xaxis.range = chart.layout.xaxis.range.slice();
  chart._fullLayout.yaxis.range = chart.layout.yaxis.range.slice();
  handlers.plotly_afterplot();
}};
axis.install(chart, () => ({
  window: history, mode: 'log', gestureActive: active,
  onNavigate: () => { navigations++; }
}));
assert.equal(updates, 0, 'Do not relayout labels while the user is dragging');
assert.equal(navigations, 0, 'Do not rebuild projection traces during a drag');

(async () => {
  active = false;
  chart._readablePriceAxis.refresh();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(chart._fullLayout.xaxis.range.map(Date.parse), future.map(Date.parse),
    'Label refresh after release must retain 2075 even when Plotly input was stale');
  assert.deepEqual(chart._fullLayout.yaxis.range, [5, 8]);
  assert.deepEqual(chart.layout.xaxis.range.map(Date.parse), future.map(Date.parse));
  assert.deepEqual(chart.layout.yaxis.range, [5, 8]);

  Object.assign(context, {
    chartData: {}, chartRenderTask: null, chartGestureActive: true,
    pendingChartRender: null
  });
  const renderStart = html.indexOf('function renderChart(options)');
  const renderEnd = html.indexOf('  if(selectedRange && !selecting)', renderStart);
  vm.runInContext(html.slice(renderStart, renderEnd) + 'return "rendered";}', context);
  await context.renderChart({fitPrices: true});
  assert.equal(context.pendingChartRender.fitPrices, true);
  context.chartGestureActive = false;
  assert.equal(context.renderChart(), 'rendered');

  const callbacks = [];
  Object.assign(context, {
    setTimeout: callback => callbacks.push(callback),
    pendingChartRender: {fitPrices: true}, chartGestureActive: true,
    pendingMarketUpdate: false
  });
  let resumed;
  context.renderChart = options => { resumed = options; };
  vm.runInContext(html.slice(html.indexOf('function finishChartGesture()'),
    html.indexOf("\ndocument.addEventListener('pointerup', finishChartGesture,")), context);
  context.finishChartGesture();
  assert.equal(context.chartGestureActive, false);
  assert.equal(resumed, undefined, 'Let Plotly finish its native mouse-up before redrawing');
  callbacks.shift()();
  assert.equal(resumed.fitPrices, true);
  assert.equal(context.pendingChartRender, null);
  assert.match(html, /options\.fitPrices && xAxisRange\[1\] > dataDateWindow\(\)\[1\]/,
    'Explicit future price fitting must not depend on the horizon dropdown');
  console.log('2075 navigation passed: displayed viewport wins over stale input, no mid-drag redraw, deferred release, synchronized labels and future-price fitting.');
})().catch(error => {console.error(error); process.exitCode = 1;});
