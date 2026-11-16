const fs=require("node:fs");
const vm=require("node:vm");
const assert=require("node:assert/strict");
const html=fs.readFileSync("components/chart_draw/index.html","utf8");
function element() {
  return {children:[],style:{},textContent:"",
    replaceChildren(){this.children=[];},append(...children){this.children.push(...children);},
    appendChild(child){this.children.push(child);},get childElementCount(){return this.children.length;}};
}
const cards=element(), section=element();
const source="function renderBenchmarkPrices() {"+
  html.split("function renderBenchmarkPrices() {")[1].split("\nvar benchmarkToggleSpecs")[0];
const context={chartData:{qqq_dates:["2026-11-13"]},
  benchmarkQuotes:{QQQ:{price:665.02,currency:"USD",source:"Schwab",
    observed_at:new Date().toISOString(),checked_at:new Date().toISOString()}},
  customStocks:{entries:()=>[]},
  document:{getElementById:id=>id==="benchmark-price-cards"?cards:section,createElement:element}};
vm.createContext(context);
vm.runInContext(source+"\nrenderBenchmarkPrices()",context);
assert.equal(cards.children.length,1);
assert.deepEqual(cards.children[0].children.map(child=>child.textContent),["QQQ","$665.02"]);
assert.equal(cards.children[0].children.length,2,"Only name and price appear, without paragraphs");
assert.equal(cards.children[0].title,undefined,"No provider commentary appears even on hover");
assert.match(cards.children[0].style.cssText,/display:flex/);
assert.doesNotMatch(html,/Quotes may be delayed; observation times are shown/);
assert.match(html,/id="benchmark-price-cards"[^>]*flex-wrap:nowrap/);
assert.match(html,/id="benchmark-price-cards"[^>]*overflow-x:auto/);
assert.doesNotMatch(html,/<strong>Latest benchmark prices<\/strong>/,'No heading creates an extra line');
context.chartData.vix_dates=["2026-11-13"];
context.benchmarkQuotes.VIX={price:21.48,unit:"points",observed_at:new Date().toISOString()};
vm.runInContext("renderBenchmarkPrices()",context);
assert.deepEqual(cards.children[1].children.map(child=>child.textContent),["VIX","21.48"]);
assert.match(cards.children[1].ariaLabel,/points/,'Index units remain available to assistive technology');
context.benchmarkQuotes={};
vm.runInContext("renderBenchmarkPrices()",context);
assert.equal(cards.children[0].children[1].textContent,"Quote unavailable","No historical value is passed off as a current quote");
console.log("Compact benchmark readouts passed: symbol and price only, no repeated visible provenance, correct unavailable state.");
