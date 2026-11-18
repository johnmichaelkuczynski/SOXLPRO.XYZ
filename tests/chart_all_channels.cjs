const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('components/chart_draw/index.html', 'utf8');
assert.match(html, /id="allChannelLinesBtn" onclick="addAllAutomaticChannelLines\(\)"/);
let undo = [], renders = 0, saved = 0;
const manual = {label:'My line', x1:'2020-01-01', x2:'2030-01-01', y1:5, y2:10};
const context = {
  chartData:{dates:['2020-01-01','2021-01-01','2022-01-01'],prices:[10,15,12]},
  lines:[manual], scaleMode:'log', selectedRange:null,
  getFutureEndMs:()=>Date.parse('2036-01-01'),
  msToDateStr:t=>new Date(t).toISOString().slice(0,10),
  announce(){}, trackEvent(){},
  saveUndoState(){undo.push(JSON.stringify(context.lines));},
  renderChart(){renders++;}, renderLineList(){},
  setComponentValue(value){assert.equal(value.action,'set_all');saved++;}
};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('function medianValue('),
  html.indexOf('\nfunction chartUndoSnapshot(')), context);
for (const scale of ['log','linear']) {
  context.scaleMode=scale;
  context.lines=[manual];undo=[];renders=0;saved=0;
  context.addAllAutomaticChannelLines();
  assert.equal(context.lines.length,4);
  assert.equal(context.lines[0],manual);
  assert.deepEqual(Array.from(context.lines.slice(1),line=>line.automaticType),['lower','median','upper']);
  assert.equal(undo.length,1,'One click creates one Undo step');
  assert.equal(renders,1);assert.equal(saved,1);
  assert.ok(context.lines.every(line=>Number.isFinite(line.y1)&&Number.isFinite(line.y2)));
  context.addAllAutomaticChannelLines();
  assert.equal(context.lines.length,4,'Repeated clicks must not duplicate channels');
  assert.equal(undo.length,1);
  context.lines=JSON.parse(undo[0]);
  assert.equal(context.lines.length,1,'Undo restores just the original drawings');
}
const edited={automaticType:'lower',label:'Edited lower',y1:8,y2:9};
context.lines=[manual,edited];undo=[];renders=0;saved=0;
context.addAllAutomaticChannelLines();
assert.equal(context.lines.length,4);
assert.equal(context.lines[1],edited,'Existing resized channels are preserved');
assert.equal(undo.length,1);
context.lines=[manual];undo=[];renders=0;saved=0;
context.selectedRange={startMs:Date.parse('2090-01-01'),endMs:Date.parse('2091-01-01')};
context.addAllAutomaticChannelLines();
assert.equal(context.lines.length,1,'Invalid selections must not create partial sets');
assert.equal(undo.length,0);assert.equal(renders,0);assert.equal(saved,0);
console.log('Draw-all channels passed: both scales, one Undo/save/redraw, no duplicates, preserved edits and atomic failure.');
