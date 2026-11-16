const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('components/chart_draw/index.html','utf8');
const source=html.slice(html.indexOf('function jumpBelowChart(event)'),html.indexOf('function parkControlRail(event)'));
let calls=[],handler,settings;
const context={window:{innerHeight:800,frameElement:{getBoundingClientRect:()=>({top:-220})}},
  document:{getElementById:()=>({getBoundingClientRect:()=>({top:1500})})},
  scrollRailParent:options=>calls.push(options),
  chartScroll:{addEventListener:(name,callback,options)=>{assert.equal(name,'wheel');handler=callback;settings=options;}},
  console};
vm.createContext(context);vm.runInContext(source,context);
function wheel(overrides={}) {
  const event={deltaY:240,deltaX:0,deltaMode:0,prevented:false,stopped:false,
    preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;},...overrides};
  handler(event);return event;
}
assert.equal(settings.capture,true);assert.equal(settings.passive,false);
let event=wheel();
assert.equal(calls.at(-1).top,240);
assert.ok(event.prevented&&event.stopped,'Wheel is forwarded once, never passed to Plotly zoom');
wheel({deltaY:-3,deltaMode:1});assert.equal(calls.at(-1).top,-60);
wheel({deltaY:1,deltaMode:2});assert.equal(calls.at(-1).top,800);
const count=calls.length;
assert.equal(wheel({ctrlKey:true}).prevented,false,'Browser zoom remains available');
assert.equal(wheel({deltaX:300}).prevented,false,'Horizontal trackpad motion remains native');
assert.equal(calls.length,count);
context.jumpBelowChart();
assert.equal(calls.at(-1).top,1204,'Button moves the actual parent page past the graph in one action');
assert.equal(calls.at(-1).behavior,'instant');
assert.match(html,/scrollZoom:\s*false/);
assert.match(html,/id="below-chart"/);
console.log('Chart navigation passed: wheel scrolls the page, browser zoom is preserved, and Below chart jumps past the plot.');
