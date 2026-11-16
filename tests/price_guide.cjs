const assert = require("node:assert/strict");
const {geometry, pointGeometry, pickPoint, horizontalLinePoints} =
  require("../components/chart_draw/price_guide.js");
const quote = {source: "Schwab", price: 50.06, observed_at: "2026-11-16T14:30:00Z"};
function layout(log) {
  return {
    xaxis: {_offset: 65, _length: 800, d2p: () => 600,
      p2d: () => "2026-11-16T14:30:00Z"},
    yaxis: {_offset: 48, _length: 600,
      d2p: p => log ? 600 - Math.log10(p) * 100 : 600 - p,
      p2d: p => log ? Math.pow(10, (600 - p) / 100) : 600 - p}
  };
}
for (const log of [false, true]) {
  const axes = layout(log);
  const point = geometry(quote, axes);
  assert.equal(point.left, 65);
  assert.equal(point.end, 665);
  assert.equal(point.y, 48 + axes.yaxis.d2p(50.06));
  assert.equal(point.endpointVisible, true);
}
assert.equal(geometry(null, layout(true)), null);
assert.equal(geometry({...quote, source: "Yahoo"}, layout(true)), null);
for (const price of [0, -1, NaN, Infinity])
  assert.equal(geometry({...quote, price}, layout(true)), null);
assert.equal(geometry({...quote, observed_at: "invalid"}, layout(true)), null);
const axes = layout(true);
axes.xaxis.d2p = () => 1000;
assert.equal(geometry(quote, axes).end, 865);
assert.equal(geometry(quote, axes).endpointVisible, false);
axes.xaxis.d2p = () => -1;
assert.equal(geometry(quote, axes), null);
axes.xaxis.d2p = () => 600;
axes.yaxis.d2p = () => 601;
assert.equal(geometry(quote, axes), null);
console.log("Price guide geometry passed: log/linear axes, quote validation and viewport clipping.");

// Exercise the real browser controller without requests or a Streamlit rerun.
const fs = require("node:fs");
const vm = require("node:vm");
function element() {
  return {style: {}, children: [], attrs: {}, handlers: {}, classList: {toggle() {}},
    namespaceURI: "http://www.w3.org/2000/svg",
    setAttribute(key, value) { this.attrs[key] = value; },
    appendChild(child) { child.isConnected = true; this.children.push(child); },
    replaceChildren() { this.children = []; },
    getBoundingClientRect() { return {left: 0, top: 0}; },
    addEventListener(event, handler) { this.handlers[event] = handler; }};
}
const toggle = element();
const pick = element(), remove = element(), status = element();
const controls = {priceGuideToggle: toggle, pickPricePoint: pick,
  removePricePoint: remove, pickedPriceStatus: status};
const chart = Object.assign(element(), {
  _fullLayout: layout(true), clientWidth: 1000, clientHeight: 900,
  on(event, handler) { this.handlers[event] = handler; }
});
const storage = {};
const windowMock = {document: {
  getElementById: id => controls[id], createElementNS: () => element()
}, addEventListener() {}};
const context = {
  window: windowMock, document: windowMock.document,
  localStorage: {getItem: key => storage[key], setItem: (key, value) => {storage[key] = value;}}
};
vm.runInNewContext(fs.readFileSync("components/chart_draw/price_guide.js", "utf8"), context);
let current = quote;
let drawnLines = [];
windowMock.installPriceGuide(chart, () => current, () => drawnLines);
const svg = chart.children[0];
assert.equal(toggle.attrs["aria-pressed"], "true");
assert.ok(svg.children.some(node => node.attrs["stroke-dasharray"] === "6 4"));
assert.ok(svg.children.some(node => node.textContent === "$50.06"));
toggle.handlers.click();
assert.equal(toggle.attrs["aria-pressed"], "false");
assert.equal(svg.children.length, 0);
assert.equal(storage["soxl-price-guide"], "off");
toggle.handlers.click();
current = {...quote, price: 51.23};
chart._priceGuide.refresh();
assert.ok(svg.children.some(node => node.textContent === "$51.23"));
current = null;
chart._priceGuide.refresh();
assert.equal(svg.children.length, 0);
assert.match(toggle.title, /No current quote/);
assert.ok(chart.handlers.plotly_afterplot);
assert.ok(chart.handlers.plotly_relayout);
console.log("Price guide controller passed: default on, immediate toggle, saved preference, quote updates and no fallback.");

for (const log of [false, true]) {
  const axes = layout(log);
  const expected = 23.45;
  const py = axes.yaxis._offset + axes.yaxis.d2p(expected);
  const result = pickPoint(axes, 665, py);
  assert.ok(Math.abs(result.price - expected) < 1e-9);
  assert.equal(result.time, quote.observed_at);
  const rendered = pointGeometry(result, axes);
  assert.ok(Math.abs(rendered.y - py) < 1e-9);
  assert.equal(pickPoint(axes, 64, py), null);
  assert.equal(pickPoint(axes, 665, 47), null);
}
assert.equal(remove.disabled, true);
pick.handlers.click();
assert.equal(pick.attrs["aria-pressed"], "true");
let target = svg.children.find(node => node.attrs["pointer-events"] === "all");
assert.ok(target, "Any plot position is clickable, not just a price trace");
let prevented = false;
target.handlers.click({clientX: 665, clientY: 448,
  preventDefault() { prevented = true; }, stopPropagation() {}});
assert.equal(prevented, true);
assert.equal(pick.attrs["aria-pressed"], "false");
assert.equal(remove.disabled, false);
assert.equal(status.textContent, "Picked price: $100.00");
assert.ok(svg.children.some(node => node.textContent === "$100.00"));
assert.ok(svg.children.some(node => node.attrs.fill === "#92400e"));
chart.handlers.plotly_relayout();
assert.ok(svg.children.some(node => node.textContent === "$100.00"),
  "Picked line survives viewport updates even without a current quote");
remove.handlers.click();
assert.equal(svg.children.length, 0);
assert.equal(remove.disabled, true);
console.log("Any-point guide passed: log/linear picking, exact highlighted price, retained selection and immediate removal.");

const horizontal = {x1: "2025-01-01", x2: "2026-11-16",
  y1: 275.42, y2: 275.42, color: "#ff9800"};
drawnLines = [horizontal];
chart.handlers.plotly_afterplot();
assert.ok(svg.children.some(node => node.textContent === "$275.42"),
  "A manually drawn horizontal line automatically labels its exact Y-axis price");
assert.ok(svg.children.some(node => node.attrs.fill === horizontal.color));
assert.equal(horizontalLinePoints([{...horizontal, y2: 500}], layout(true)).length, 0,
  "Sloping trendlines are not mislabeled as horizontal guides");
const reverse = {...horizontal, x1: horizontal.x2, x2: horizontal.x1};
assert.equal(horizontalLinePoints([reverse], layout(true))[0].price, 275.42);
drawnLines = [];
chart.handlers.plotly_afterplot();
assert.equal(svg.children.length, 0, "Deleting or undoing a line removes its price label");
console.log("Hand-drawn horizontal guides passed: automatic exact label, matching color, reversed draw and removal.");

let undoSaved = 0, measurementRemoved = false;
windowMock.saveUndoState = () => { undoSaved++; };
chart._axisArea = {restore: value => { measurementRemoved = value === null; }};
chart.handlers.dblclick({
  altKey: false, target: {closest: () => null}, clientX: 665, clientY: 448,
  preventDefault() {}, stopImmediatePropagation() {}
});
assert.equal(undoSaved, 1);
assert.equal(measurementRemoved, true);
assert.ok(svg.children.some(node => node.textContent === "$100.00"),
  "Double-click alone creates the exact-price horizontal guide");
console.log("Direct double-click passed: creates a guide without another button and removes the measurement overlay.");

// Plotly often suppresses native dblclick entirely. Exercise the actual
// pointer down/up sequence, not just a manually dispatched dblclick event.
chart._priceGuide.restore(null);
undoSaved = 0;
const pointer = (x, y) => ({
  button:0, pointerId:1, clientX:x, clientY:y,
  target:{closest:()=>null}
});
function tap(x, y) {
  chart.handlers.pointerdown(pointer(x,y));
  chart.handlers.pointerup(pointer(x,y));
}
tap(665,348);
assert.equal(undoSaved,0,"A single click does not create a guide");
tap(665,348);
assert.equal(undoSaved,1,"Two pointer taps create one undoable guide without native dblclick");
assert.ok(svg.children.some(node=>node.textContent==="$1,000.00"));
chart.handlers.dblclick({
  ...pointer(665,348), preventDefault(){},stopImmediatePropagation(){}
});
assert.equal(undoSaved,1,"A subsequent native dblclick does not duplicate the action");
chart._priceGuide.restore(null);
undoSaved=0;
chart.handlers.pointerdown(pointer(665,448));
chart.handlers.pointermove(pointer(665,430));
chart.handlers.pointermove(pointer(665,448));
chart.handlers.pointerup(pointer(665,448));
tap(665,448);
assert.equal(undoSaved,0,"A drag returning to its origin is not counted as a click");
console.log("Plotly-safe double-click passed: pointer-only gesture, no single-click action, no pan false positive and no duplicate undo.");
