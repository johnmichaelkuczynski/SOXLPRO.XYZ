const assert = require("node:assert/strict");
const {resize, priceAt, handles} = require("../components/chart_draw/channel_resize.js");
const DAY = 86400000;
const start = Date.parse("2020-01-01"), end = start + 100 * DAY;
const line = {x1_ms: start, x2_ms: end, x1: "2020-01-01", x2: "2020-04-10",
  y1: 10, y2: 100, automaticType: "median", label: "Median Line", color: "#475569"};
const date = value => new Date(value).toISOString().slice(0, 10);
for (const kind of ["median", "upper", "lower"]) {
  for (const scale of ["log", "linear"]) {
    const original = {...line, automaticType: kind};
    const short = resize(original, 2, start + 50 * DAY, scale, date);
    assert.equal(short.x2_ms, start + 50 * DAY);
    const expected = scale === "log" ? Math.sqrt(1000) : 55;
    assert.ok(Math.abs(short.y2 - expected) < 1e-8);
    assert.equal(short.x1_ms, start);
    assert.equal(short.y1, 10);
    assert.equal(short.automaticType, kind);
    assert.equal(short.manualExtent, true);
    const longer = resize(short, 2, start + 150 * DAY, scale, date);
    assert.ok(Math.abs(longer.y2 - priceAt(original, start + 150 * DAY, scale)) < 1e-8);
    const laterStart = resize(original, 1, start + 20 * DAY, scale, date);
    assert.equal(laterStart.x2_ms, end);
    assert.ok(Math.abs(laterStart.y1 - priceAt(original, start + 20 * DAY, scale)) < 1e-8);
    assert.equal(resize(original, 1, end, scale, date), null);
    assert.equal(resize(original, 2, start, scale, date), null);
    assert.equal(original.y2, 100, "Original undo snapshot is not mutated");
  }
}
const layout = {
  xaxis: {_offset: 65, _length: 800, d2p: v => (Number(v) - start) / DAY * 10},
  yaxis: {_offset: 48, _length: 600, d2p: v => 500 - Math.log10(v) * 100}
};
const points = handles(line, layout, 600);
assert.equal(points.length, 2);
assert.ok(points.every(point => point.x >= 75 && point.x <= 600));
assert.equal(handles({...line, automaticType: null}, layout).length, 0);
console.log("Channel resize passed: all channel types, both ends, preserved log/linear slopes, undo safety and off-screen handles.");
