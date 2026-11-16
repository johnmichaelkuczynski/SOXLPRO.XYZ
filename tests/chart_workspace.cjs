const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {priceAt} = require("../components/chart_draw/channel_resize.js");
const html = fs.readFileSync("components/chart_draw/index.html", "utf8");
const consoleLayer = Number(html.match(/#toolbar\s*\{[^}]*z-index:\s*(\d+)/)[1]);
const barLayer = Number(html.match(/<div id="chart-view-bar"[^>]*z-index:(\d+)/)[1]);
assert.ok(consoleLayer > barLayer, "The chart console must stay above the view bar when dragged across it.");
assert.ok(
  html.indexOf('id="stock-entry-controls"') < html.indexOf('id="benchmark-controls"'),
  "The stock-entry panel must occupy the first console cell, beside benchmarks in the wide layout."
);
assert.ok(
  html.indexOf('id="custom-stock-form"') < html.indexOf('id="benchmark-controls"'),
  "Stock input must not be buried inside the benchmark section."
);
assert.match(html, />Add a stock ticker<\/label>/);
const source = html.split("function showChannelPricesForDate() {")[1].split("\nvar sizeGrip =")[0];
assert.ok(source);
const start = Date.parse("2020-01-01T12:00:00Z");
const types = ["lower", "median", "upper"];
const lines = types.map((kind, index) => ({
  automaticType: kind, x1_ms: start, x2_ms: start + 100 * 86400000,
  y1: [5, 10, 20][index], y2: [50, 100, 200][index]
}));
const input = {value: "2020-01-01"}, output = {};
const context = {lines, scaleMode: "log", SOXLChannelResize: {priceAt},
  document: {getElementById: id => id === "channel-price-date" ? input : output},
  addAutomaticChannelLine() { throw Error("Existing lines must not be replaced"); }};
vm.createContext(context);
vm.runInContext("function showChannelPricesForDate() {" + source + "\nshowChannelPricesForDate();", context);
assert.match(output.textContent, /Low: \$5\.00.*Median: \$10\.00.*High: \$20\.00/);
assert.match(output.textContent, /not actual daily trading highs\/lows/);
lines[0].y1 = 3;
vm.runInContext("showChannelPricesForDate()", context);
assert.match(output.textContent, /Low: \$3\.00/);
input.value = "";
vm.runInContext("showChannelPricesForDate()", context);
assert.equal(output.textContent, "Choose a date first.");
assert.match(html, /width: calc\(100% - 308px\)/);
assert.match(html, /id="chart-size-grip"/);
assert.ok(html.indexOf('id="chart-action-row"') < html.indexOf('id="chart-scroll"'));
const measurement = fs.readFileSync("components/chart_draw/area_measure.js", "utf8");
assert.doesNotMatch(measurement, /opacity:0\.12/);
console.log("Workspace passed: date-specific channel prices, refreshed values, reserved console space, outside actions, resize grip and no beige fill.");
