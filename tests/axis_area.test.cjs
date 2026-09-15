const {test} = require("node:test");
const assert = require("node:assert/strict");
const {measure} = require("../components/chart_draw/area_measure.js");

test("linear area is price difference times elapsed calendar days", () => {
  const result = measure("2026-01-11", 200, "2026-01-01", 0, false);
  assert.equal(result.days, 10);
  assert.equal(result.dollarDays, 2000);
  assert.equal(result.axisArea, 2000);
});
test("log area is distinct from dollar-days and uses the positive axis floor", () => {
  const result = measure("2026-01-11", 100, "2026-01-01", 1, true);
  assert.equal(result.dollarDays, 990);
  assert.equal(result.axisArea, 20);
});
test("nonzero axis origin and reversed coordinates give unsigned geometric area", () => {
  assert.equal(measure("2026-01-01", 10, "2026-01-11", 20, false).axisArea, 100);
  assert.equal(measure("2026-01-01", 10, "2026-01-01", 10, true).axisArea, 0);
});
test("invalid coordinates and zero log baselines are rejected", () => {
  assert.equal(measure("bad-date", 10, "2026-01-01", 1, true), null);
  assert.equal(measure("2026-01-11", 100, "2026-01-01", 0, true), null);
  assert.equal(measure("2026-01-11", Infinity, "2026-01-01", 1, true), null);
});