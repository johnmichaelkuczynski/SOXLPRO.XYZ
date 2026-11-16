const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
function element() {
  return {style: {}, children: [], handlers: {}, attrs: {},
    setAttribute(key, value) { this.attrs[key] = value; },
    appendChild(child) { this.children.push(child); },
    addEventListener(event, fn) { this.handlers[event] = fn; }};
}
const parent = {body: element(), getElementById() { return null; }, createElement: element};
const actionRow = element();
const frame = {body: element(), createElement: element,
  getElementById: id => id === "chart-action-row" ? actionRow : null};
const window = {parent: {document: parent}};
vm.runInNewContext(fs.readFileSync("components/chart_draw/page_actions.js", "utf8"),
  {window, document: frame});
let clears = 0, undos = 0;
const api = window.installPageActions({clear: () => clears++, undo: () => undos++});
assert.equal(parent.body.children.length, 0, "Buttons do not float over the parent page");
assert.equal(frame.body.children.length, 0);
const box = actionRow.children[0];
assert.match(box.style.cssText, /flex-direction:row/);
assert.doesNotMatch(box.style.cssText, /position:fixed/);
assert.deepEqual(box.children.map(child => child.textContent), ["Clear All", "Undo"]);
box.children[0].handlers.click();
box.children[1].handlers.click();
assert.equal(clears, 1);
assert.equal(undos, 1);
api.update(1);
assert.match(box.children[1].title, /last chart change/);
const html = fs.readFileSync("components/chart_draw/index.html", "utf8");
assert.match(html, /window\.parent\.location\.reload\(\)/);
assert.match(html, /axisArea\.restore\(previous\.axisArea\)/);
assert.match(html, /priceGuide\.restore\(previous\.priceGuide\)/);
console.log("Page actions passed: side-by-side buttons above the graph, no floating overlay and immediate callbacks.");
