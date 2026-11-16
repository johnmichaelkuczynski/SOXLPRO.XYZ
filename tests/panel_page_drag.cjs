const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const portal = require('../components/chart_draw/page_console.js');
const html = fs.readFileSync('components/chart_draw/index.html', 'utf8');
const source = html.slice(
  html.indexOf("toolbarEl.addEventListener('pointerdown', function(event)"),
  html.indexOf("\ndocument.querySelectorAll('.rail-resize-handle')")
);

function fixture(search = '') {
  const toolbarListeners = new Map(), documentListeners = new Map(), frames = new Map();
  let nextFrame = 0, captured = false;
  const scrolls = [];
  const ownerWindow = {
    requestAnimationFrame(fn) { frames.set(++nextFrame, fn); return nextFrame; },
    cancelAnimationFrame(id) { frames.delete(id); },
  };
  const ownerDocument = {
    defaultView: ownerWindow,
    addEventListener(type, fn) { documentListeners.set(type, fn); },
    removeEventListener(type) { documentListeners.delete(type); },
  };
  const rect = {left:800, top:600, width:280, height:280, right:1080, bottom:880};
  const toolbar = {
    style:{height:'720px'}, clientWidth:280, clientLeft:0,
    ownerDocument,
    getBoundingClientRect() { return {...rect}; },
    setPointerCapture() { captured = true; },
    hasPointerCapture() { return captured; },
    releasePointerCapture() { captured = false; },
    addEventListener(type, fn) { toolbarListeners.set(type, fn); },
    removeEventListener(type) { toolbarListeners.delete(type); },
  };
  const lines = [{x1:1, y1:5, x2:2, y2:6}];
  const context = vm.createContext({
    toolbarEl:toolbar, pageConsole:{active:true}, SOXLFloatingConsole:portal,
    railManuallySized:false, railResponsiveDock:true, railDock:'right',
    railFreeLeft:null, railFreeTop:null, suppressPanelClick:false, lines,
    URLSearchParams,
    window:{
      location:{search}, parent:{innerHeight:900},
      frameElement:{getBoundingClientRect:()=>({top:600})},
      requestAnimationFrame() { throw Error('Do not use the offscreen child frame clock'); },
    },
    scrollRailParent(options) { scrolls.push(options.top); },
    positionRightControlRail() {},
  });
  vm.runInContext(source, context);
  const pointer = (x, y) => ({
    button:0, pointerId:7, pointerType:'mouse', clientX:x, clientY:y,
    target:{closest:()=>false}, preventDefault(){},
  });
  const start = () => toolbarListeners.get('pointerdown')(pointer(830,615));
  const move = (x, y) => documentListeners.get('pointermove')(pointer(x,y));
  const tick = () => {
    const [id, fn] = frames.entries().next().value;
    frames.delete(id);
    fn();
  };
  return {context, toolbarListeners, documentListeners, frames, scrolls, start, move, tick};
}

for (const finish of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  const test = fixture(), before = JSON.stringify(test.context.lines);
  test.start();
  test.move(400,10);
  assert.equal(test.context.railDock, 'free');
  assert.equal(test.context.railFreeLeft, 370);
  test.tick();
  assert.ok(test.scrolls[0] < 0, 'Dragging at the upper page edge scrolls upward.');
  test.tick();
  assert.equal(test.scrolls.length,2,'A stationary held pointer continues page scrolling.');
  const pending = [...test.frames.values()][0];
  const listener = finish === 'lostpointercapture'
    ? test.toolbarListeners.get(finish) : test.documentListeners.get(finish);
  listener();
  assert.equal(test.frames.size,0,'Release/cancel/lost capture stops the page scroll loop.');
  pending();
  assert.equal(test.scrolls.length,2,'A late callback cannot resume scrolling after release.');
  assert.equal(test.documentListeners.size,0);
  assert.equal(test.context.suppressPanelClick,true);
  assert.equal(JSON.stringify(test.context.lines),before,'Moving controls must not change chart lines.');
}
const lower = fixture();
lower.start(); lower.move(400,890); lower.tick();
assert.ok(lower.scrolls[0] > 0,'The lower page edge scrolls downward.');
lower.documentListeners.get('pointerup')();

const isolated = fixture('?diagnostics_sandbox=1');
isolated.start(); isolated.move(400,10); isolated.tick();
assert.equal(isolated.scrolls.length,0,'An isolated diagnostic must not scroll the user page.');
isolated.documentListeners.get('pointerup')();
console.log('Panel page drag passed: continuous edge scroll, parent animation clock, release/cancel cleanup and unchanged line model.');
