const assert = require("node:assert/strict");
const {normalize, scaled, install} = require("../components/chart_draw/custom_stocks.js");
assert.equal(normalize(" msft "), "MSFT");
assert.throws(() => normalize("../path"));
const base = {dates:["2026-01-01","2026-01-02"], prices:[10,20]};
assert.deepEqual(scaled({dates:base.dates,prices:[100,150]},base),[10,15]);
assert.throws(() => scaled({dates:["2020-01-01"],prices:[1]},base), /no trading dates/);
function element() {
  return {children:[],handlers:{},style:{},value:"",disabled:false,
    appendChild(child){this.children.push(child);},
    replaceChildren(){this.children=[];},
    setAttribute(){},addEventListener(name, fn){this.handlers[name]=fn;}};
}
const nodes = Object.fromEntries(["custom-stock-form","custom-stock-symbol","custom-stock-add",
  "custom-stock-status","custom-stock-list"].map(id=>[id,element()]));
const doc = {getElementById:id=>nodes[id],createElement:element,createTextNode:text=>({textContent:text})};
let requests=0, changes=0;
const controller = install({document:doc,base:()=>base,changed:()=>changes++,
  fetch:async url=>{
    requests++;
    const symbol = new URL(url,"https://example.test").searchParams.get("symbol");
    if (symbol==="INVALID") return {ok:false,json:async()=>({error:"No daily price history was found."})};
    return {ok:true,json:async()=>({symbol,dates:base.dates,prices:[100,150],
      source:"test provider",through:"2026-01-02"})};
  }});
const submit = async symbol=>{
  nodes["custom-stock-symbol"].value=symbol;
  await nodes["custom-stock-form"].handlers.submit({preventDefault(){}});
};
(async()=>{
  await submit("AAPL");
  await submit("MSFT");
  assert.equal(controller.entries().length,2);
  assert.equal(controller.traces(base).length,2);
  assert.equal(controller.traces(base)[0].name,"AAPL");
  assert.deepEqual(controller.traces(base)[0].customdata,[100,150]);
  assert.deepEqual(controller.traces(base)[0].y,[10,15]);
  await submit("AAPL");
  assert.equal(requests,2,"Duplicate symbols do not spend another provider request");
  const toggle=nodes["custom-stock-list"].children[0].children[0].children[0];
  toggle.checked=false;toggle.handlers.change();
  assert.equal(controller.traces(base).length,1);
  nodes["custom-stock-list"].children[0].children[1].handlers.click();
  assert.deepEqual(controller.entries().map(stock=>stock.symbol),["MSFT"]);
  await submit("INVALID");
  assert.match(nodes["custom-stock-status"].textContent,/No daily price history/);
  assert.equal(controller.entries().length,1,"A failed symbol does not remove existing lines");
  assert.equal(nodes["custom-stock-add"].disabled,false);
  assert.ok(changes>=4);
  assert.deepEqual(base.prices,[10,20],"SOXL data is untouched");
  console.log("Custom stocks passed: multiple symbols, normalization, Enter/submit, duplicate protection, visibility, remove and explicit errors.");
})().catch(error=>{console.error(error);process.exitCode=1;});
