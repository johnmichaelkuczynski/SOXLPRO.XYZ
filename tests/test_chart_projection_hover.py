"""Exercise the real hover handler independently of the market-data feed."""
import subprocess
import unittest
from pathlib import Path


class ProjectionHoverTests(unittest.TestCase):
    def test_readouts_remain_available_in_selection_mode(self):
        html = Path("components/chart_draw/index.html").read_text()
        handler = html.split("function inspectTrendLine(event) {", 1)[1].split(
            "\nchartContainer.addEventListener('pointermove'", 1
        )[0]
        script = """
const assert = require('node:assert/strict');
var currentMode = 'select', selecting = false, scaleMode = 'log';
var lastProjectionPointer, hoveredLineIndex, hoveredLineDistance;
var requested = '', active = false;
var trendTooltip = {
  style: {}, offsetWidth: 280, offsetHeight: 120, children: [],
  replaceChildren() { this.children = []; },
  appendChild(child) { this.children.push(child); }
};
var document = {
  body: {classList: {
    remove() { active = false; }, add() { active = true; }
  }},
  getElementById() { return {value: requested}; },
  createElement() { return {}; }
};
var window = {innerHeight: 900, innerWidth: 1200};
var start = Date.parse('2020-01-01'), end = Date.parse('2035-01-01');
var lines = [
  {x1: start, x2: end, y1: 100, y2: 100, color: '#e33', label: 'Upper'},
  {x1: start, x2: end, y1: 10, y2: 10, color: '#555', label: 'Middle'},
  {x1: start, x2: end, y1: 1, y2: 1, color: '#393', label: 'Lower'}
];
var COLORS = [], projectionAnalyticsSeen = new Set();
var chartData = {dates: ['2026-10-21']};
var chartDiv = {
  _fullLayout: {
    _size: {l:65, t:48, w:1000, h:600},
    xaxis: {range:[start,end]}, yaxis: {range:[-1,3]}
  },
  getBoundingClientRect() { return {left:0,top:0}; }
};
function lineTimestamp(line, index) { return line['x'+index]; }
function getFutureEndMs() { return end; }
function formatProjectedDate() { return 'Jan 1, 2030'; }
function formatHitProbability() { return '42.0%'; }
function estimateHitProbability() { return null; }
function getHitProbabilityModel() { return null; }
""" + "\nfunction inspectTrendLine(event) {" + handler + """
// 2030 is future space. Each line must own its own popup and price.
const x = 65 + (Date.parse('2030-01-01') - start) / (end-start)*1000;
for (const mode of ['pan', 'select', 'draw']) {
  currentMode = mode;
  for (let index=0; index<3; index++) {
    const y = 48 + (index+1)*150;
    inspectTrendLine({clientX:x, clientY:y});
    assert.equal(trendTooltip.style.display, 'block');
    assert.equal(hoveredLineIndex, index);
    assert.equal(trendTooltip.style.backgroundColor, lines[index].color);
    assert.ok(trendTooltip.children.some(c =>
      c.textContent === 'Projected SOXL price: $'+lines[index].y1.toFixed(2)));
    assert.ok(active);
  }
}
currentMode = 'select';
selecting = true;
inspectTrendLine({clientX:x, clientY:498});
assert.equal(trendTooltip.style.display, 'none');
assert.equal(active, false);
selecting = false;
inspectTrendLine({clientX:x, clientY:498});
assert.equal(trendTooltip.style.display, 'block');
// Explicit lower-line choice must work even near the upper line.
requested = '2';
inspectTrendLine({clientX:x, clientY:198});
assert.equal(hoveredLineIndex, 2);
assert.equal(trendTooltip.style.backgroundColor, '#393');
"""
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
