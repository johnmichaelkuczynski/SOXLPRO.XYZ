const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('components/chart_draw/index.html', 'utf8');
const axis = require('../components/chart_draw/price_axis.js');
const channel = require('../components/chart_draw/channel_resize.js');
const elements = Object.fromEntries([
  'channel-price-date', 'channel-date-prices', 'inclination-slider', 'inclination-value'
].map(id => [id, {value: id === 'inclination-slider' ? '100' : '', textContent: ''}]));
let updates = [], frameUpdates = 0;
const history = ['2020-01-01', '2021-01-01'];
const future = ['2070-01-01', '2080-01-01'];
const context = {
  document: {getElementById: id => elements[id], body: {scrollHeight: 1500}},
  chartData: {dates: history, prices: [10, 20]},
  chartDiv: {
    layout: {xaxis: {range: history}, yaxis: {range: [-1, 3]}},
    _fullLayout: {xaxis: {range: future}, yaxis: {range: [1, 3]}}
  },
  chartScroll: {scrollLeft: 0, scrollTop: 0},
  currentChartHeight: 650, scaleMode: 'log',
  lines: [], selectedRange: null,
  SOXLPriceAxis: axis, SOXLChannelResize: channel,
  msToDateStr: timestamp => new Date(timestamp).toISOString().slice(0, 10),
  getFutureEndMs: () => Date.parse('2036-01-01'),
  setFrameHeight: () => {frameUpdates++;},
  announce: () => {},
  Plotly: {relayout: async (chart, update) => {
    updates.push(update);
    for (const [key, value] of Object.entries(update)) {
      const [name, property] = key.split('.');
      chart.layout[name][property] = value;
      chart._fullLayout[name][property] = value;
    }
  }}
};
vm.createContext(context);
function load(start, end) {
  vm.runInContext(html.slice(html.indexOf(start), html.indexOf(end, html.indexOf(start))), context);
}
load('function captureChartViewport()', '\nfunction renderChart(options)');
load('var sliderInclinationBase = null;', '\nfunction setChartWidth(');
load('function medianValue(', '\nfunction chartUndoSnapshot(');
load('var channelDateReadoutActive = false;', '\nvar sizeGrip =');
// An untouched date field must produce prices immediately, not an inert first click.
context.showChannelPricesForDate();
assert.equal(elements['channel-price-date'].value, '2021-01-01');
assert.match(elements['channel-date-prices'].textContent, /Low: \$20\.\d\d.*Median: \$20\.\d\d.*High: \$20\.\d\d/);
assert.ok(frameUpdates > 0, 'Keep results inside the visible component');
assert.equal(context.lines.length, 0, 'Reading prices must not add drawings or create undo state');
elements['channel-price-date'].value = '2030-01-01';
context.showChannelPricesForDate();
assert.match(elements['channel-date-prices'].textContent, /2030-01-01/);
assert.doesNotMatch(elements['channel-date-prices'].textContent, /unavailable|NaN|Infinity/);
// Existing edited lines, rather than newly calculated channels, own their readouts.
context.lines = ['lower', 'median', 'upper'].map((kind, i) => ({
  automaticType: kind, x1_ms: Date.parse('2020-01-01'), x2_ms: Date.parse('2040-01-01'),
  y1: (i + 1) * 10, y2: (i + 1) * 10
}));
const originalLines = JSON.stringify(context.lines);
context.showChannelPricesForDate();
assert.match(elements['channel-date-prices'].textContent, /Low: \$10\.00.*Median: \$20\.00.*High: \$30\.00/);
context.chartData = null;
context.showChannelPricesForDate();
assert.match(elements['channel-date-prices'].textContent, /need at least two SOXL prices/);
context.chartData = {dates: history, prices: [10, 20]};

(async () => {
  context.captureInclinationBase();
  await context.applyInclinationSlider(50);
  assert.deepEqual(Array.from(context.chartDiv._fullLayout.yaxis.range), [0, 4]);
  assert.deepEqual(Array.from(context.chartDiv._fullLayout.xaxis.range), future,
    'Incline must preserve the displayed future dates, not stale historical input');
  assert.equal(elements['inclination-value'].textContent, '50%');
  assert.equal(JSON.stringify(context.lines), originalLines, 'Only visual slope changes');
  await context.applyInclinationSlider(100);
  assert.deepEqual(Array.from(context.chartDiv._fullLayout.yaxis.range), [1, 3],
    'Dragging back to 100% restores the original logarithmic coordinates');
  await context.applyInclinationSlider(180);
  assert.ok(context.chartDiv._fullLayout.yaxis.range[1] - context.chartDiv._fullLayout.yaxis.range[0] < 2);
  for (const update of updates) {
    assert.ok(update['yaxis.ticktext'].length >= 5 && update['yaxis.ticktext'].length <= 8);
    assert.ok(update['yaxis.ticktext'].every(label => !/[eE][+-]?\d/.test(label)));
  }
  context.resetInclinationSlider();
  assert.equal(elements['inclination-value'].textContent, '100%');
  context.scaleMode = 'linear';
  context.chartDiv._fullLayout.yaxis.range = [10, 50];
  context.captureInclinationBase();
  await context.applyInclinationSlider(20);
  assert.deepEqual(Array.from(context.chartDiv._fullLayout.yaxis.range), [0, 200],
    'Linear flattening never introduces negative prices');
  assert.equal(JSON.stringify(context.lines), originalLines);
  assert.match(html, /if \(options\.resetViewport \|\| options\.fitPrices\) resetInclinationSlider\(\)/);
  console.log('Channel prices and incline passed: first-click values, future dates, edited channels, log/linear visual slope, stable future viewport and unchanged lines.');
})().catch(error => {console.error(error); process.exitCode = 1;});
