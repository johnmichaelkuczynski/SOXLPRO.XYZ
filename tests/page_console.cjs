const assert=require("node:assert/strict");
const fs=require("node:fs");
const portal=require("../components/chart_draw/page_console.js");
const viewport={width:1280,height:900,header:48};
const frame={left:80,right:1200,top:500};
const plot={top:300,bottom:950,parking:1000};
const base={dock:"free",left:300,top:80,width:280,height:720};
const free=portal.placement(base,viewport,frame,plot);
assert.equal(free.top,80);
assert.ok(free.top<frame.top,"The console can move above the ENTIRE embedded chart frame.");
assert.equal(free.left,300);
assert.equal(free.maxHeight,720);
assert.ok(free.visible);
const edges=portal.placement({...base,left:2000,top:-500},viewport,frame,plot);
assert.equal(edges.left,992);
assert.equal(edges.top,8,"Free movement includes the page-header area, not only the chart.");
const bottomEdge=portal.placement({...base,top:5000},viewport,frame,plot);
assert.ok(bottomEdge.top+bottomEdge.maxHeight<=viewport.height-8,
  "A free panel must retain a reachable internal scroll area at the bottom edge.");
for(const top of [8,80,250,500]) {
  const box=portal.placement({...base,top},viewport,{...frame,top:1500},plot);
  assert.equal(box.top,top,"The offscreen chart must not constrain page-wide placement.");
  assert.ok(box.visible);
}
assert.ok(portal.edgeScrollVelocity(10,900)<0);
assert.ok(portal.edgeScrollVelocity(890,900)>0);
assert.equal(portal.edgeScrollVelocity(450,900),0);
assert.equal(portal.edgeScrollVelocity(NaN,900),0);
const docked=portal.placement({...base,dock:"right"},viewport,frame,plot);
assert.equal(docked.left,908);
assert.equal(docked.top,812);
assert.equal(docked.visible,false,"Do not show a tiny console before the chart enters view.");
const scrolled=portal.placement({...base,dock:"right"},viewport,{...frame,top:-250},plot);
assert.equal(scrolled.top,62);
assert.equal(scrolled.maxHeight,720);
const below=portal.placement({...base,dock:"bottom",left:200},viewport,{...frame,top:-900},plot);
assert.equal(below.top,112);
assert.equal(below.left,280);
const css=portal.scopeRules([
  {selectorText:"body",style:{cssText:"overflow:hidden"}},
  {selectorText:"*, #toolbar",style:{cssText:"box-sizing:border-box"}},
  {conditionText:"(max-width:760px)",cssRules:[
    {selectorText:".tbtn",style:{cssText:"width:100%"}}
  ]}
],"#soxl-floating-console");
assert.doesNotMatch(css,/overflow:hidden/);
assert.match(css,/#soxl-floating-console \*,#soxl-floating-console #toolbar/);
assert.match(css,/@media \(max-width:760px\)\{#soxl-floating-console \.tbtn/);
const oldFrame=global.frameElement,oldLocation=global.location;
global.frameElement={};global.location={search:"?diagnostics_sandbox=1"};
assert.equal(portal.install({}),null,"Isolated diagnostics must never move controls into the user's page.");
global.frameElement=oldFrame;global.location=oldLocation;
const html=fs.readFileSync("components/chart_draw/index.html","utf8");
assert.match(html,/var pointerDocument = toolbarEl\.ownerDocument/);
assert.match(html,/pointerDocument\.addEventListener\('pointermove', moveRail\)/);
assert.match(html,/pointerDocument\.addEventListener\('pointermove', resizeRail\)/);
assert.match(html,/handle\.setPointerCapture\(event\.pointerId\)/);
assert.match(html,/pageConsole && pageConsole\.active/);
assert.match(html,/requestAnimationFrame\(scrollAtPageEdge\)/);
assert.match(html,/cancelAnimationFrame\(edgeScrollFrame\)/);
assert.match(html,/pointerDocument\.defaultView \|\| window/,
  "Use the owning page's animation clock when the chart iframe scrolls out of view.");
assert.match(html,/toolbarEl\.addEventListener\('lostpointercapture', stopMoving/);
assert.match(html,/editrevision: JSON\.stringify\(lines\)/,
  "Plotly must discard temporary drawn shapes when the persisted line model changes.");
console.log("Page console passed: above-frame movement, viewport bounds, docking, scoped styles, parent-document pointers, resizing capture and diagnostics isolation.");
