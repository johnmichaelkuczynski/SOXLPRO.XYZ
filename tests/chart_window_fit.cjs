const assert=require('node:assert/strict'),fs=require('node:fs');
const axis=require('../components/chart_draw/price_axis.js');
const dates=['2020-01-01','2020-02-01','2024-01-01','2024-02-01'];
const soxl={name:'SOXL',x:dates,y:[1,2,40,60]};
const hidden={name:'QQQ',visible:false,x:dates,y:[1e70,1e75,1e78,1e80]};
const projection={name:'Future channel',meta:{channelLineIndex:0},x:dates,y:[1e70,1e75,1e78,1e80]};
const overlay={name:'TQQQ',x:dates,y:[2,3,50,90]};
const full=['2020-01-01T00:00:00Z','2024-02-01T23:59:59.999Z'];
const recent=['2024-01-01T00:00:00Z','2024-02-01T23:59:59.999Z'];
const result=axis.fitWindow([soxl,hidden,projection],recent,'log');
assert.equal(result.min,40);assert.equal(result.max,60);assert.equal(result.count,2);
const span=Math.log10(60)-Math.log10(40);
assert.ok(Math.abs(result.range[0]-(Math.log10(40)-span*.075))<1e-12);
assert.ok(Math.abs(result.range[1]-(Math.log10(60)+span*.075))<1e-12);
assert.ok(result.range[1]<2,'Plotly log ranges contain exponents, never dollar prices');
const withOverlay=axis.fitWindow([soxl,overlay,projection],recent,'log');
assert.equal(withOverlay.max,90,'Visible normalized overlay is included');
assert.equal(axis.fitWindow([soxl,hidden,projection],full,'log').min,1,'Earlier prices return only for the full window');
assert.equal(axis.fitWindow([soxl],['2022-01-01','2022-02-01'],'log'),null,'Empty windows are explicit, never synthetic');
assert.equal(axis.fitWindow([{x:dates,y:[0,-1,NaN,Infinity]}],full,'log'),null);
assert.equal(axis.fitWindow([soxl],recent,'log',{price:1e78,observed_at:'2090-01-01'}).max,60);
assert.equal(axis.fitWindow([soxl],recent,'log',{price:65,observed_at:'2024-02-01'}).max,65);
const linear=axis.fitWindow([soxl],recent,'linear');
assert.deepEqual(linear.range,[38.5,61.5]);
for(const mode of ['log','linear']) for(const height of [212,562,1200]) {
  const range=mode==='log'?result.range:linear.range;
  const config=axis.ticks(range,height,mode);
  assert.ok(config.tickvals.length>=5&&config.tickvals.length<=8);
  assert.equal(new Set(config.ticktext).size,config.ticktext.length);
  assert.ok(config.ticktext.every(text=>text.startsWith('$')&&!/[eE][+-]?\d/.test(text)));
  for(let i=1;i<config.tickvals.length;i++) {
    const f=value=>mode==='log'?Math.log10(value):value;
    assert.ok((f(config.tickvals[i])-f(config.tickvals[i-1]))/(range[1]-range[0])*height>=30);
  }
}
assert.deepEqual(axis.dateRange(['1950-01-01','3200-01-01'],full),full.map(Date.parse));
assert.deepEqual(axis.dateRange(['2024-01-01 00:00:00','2024-02-01 23:59:59.999'],full),recent.map(Date.parse),'Plotly timezone-less coordinates are UTC');
const html=fs.readFileSync('components/chart_draw/index.html','utf8');
assert.match(html,/id="inclination-slider"/);
assert.match(html,/Chart incline/);
assert.match(html,/function resetView\(\)[\s\S]*?return renderChart\(\{resetViewport:true\}\)/);
assert.match(html,/futureHorizonYears = 0/);
assert.match(html,/fitWindow\(traces,xAxisRange,scaleMode,latestMarketQuote,fitOptions\)/);
assert.match(html,/id="show-future" onclick="showFutureProjection\(\)"/);
assert.doesNotMatch(html,/minallowed: new Date\(dateWindow/);
const future=['2030-01-01','2035-01-01'];
assert.deepEqual(axis.navigationDateRange(future,full),future.map(Date.parse));
assert.deepEqual(axis.navigationDateRange(['2090-01-01','3200-01-01'],full),full.map(Date.parse));
assert.deepEqual(axis.navigationPriceRange([1,3],'log',result.range),[1,3]);
assert.deepEqual(axis.navigationPriceRange([60,78],'log',result.range),result.range);
const futureLine={meta:{channelLineIndex:0},x:future,y:[100,250]};
assert.equal(axis.fitWindow([futureLine],future,'log'),null);
assert.equal(axis.fitWindow([futureLine],future,'log',null,{includeProjections:true}).max,250);
for(const x of [
  future.map(value=>new Date(value)),
  require('node:vm').runInNewContext("['2030-01-01','2035-01-01'].map(value=>new Date(value))")
]) {
  const datedProjection={meta:{channelLineIndex:0},x,y:[100,250]};
  assert.equal(axis.fitWindow([datedProjection],future,'log',null,{includeProjections:true})?.max,250,
    'Actual projection traces contain Date objects, including dates from another window');
}
assert.equal(axis.fitWindow([projection],full,'log',null,{includeProjections:true}),null,
  'Even explicit projection fitting rejects astronomical extrapolation values');
// Exercise the actual controller, including an extreme range during a pending update.
let updates=0;const handlers={};
const chart={data:[soxl,projection],layout:{yaxis:{}},_fullLayout:{
  xaxis:{range:recent},yaxis:{range:[60,78],type:'log',_length:562,autorange:false}},
  on:(name,callback)=>{handlers[name]=callback;}};
global.Plotly={relayout:(_chart,update)=>{
  assert.ok(++updates<8,'Fitting must converge, not enter a render loop');
  for(const [key,value] of Object.entries(update)) {
    const [name,property]=key.split('.');
    chart.layout[name]??={};chart.layout[name][property]=value;
    if(property==='range'||property==='autorange') chart._fullLayout[name][property]=value;
  }
  handlers.plotly_afterplot?.();
  return Promise.resolve();
}};
(async()=>{
  axis.install(chart,()=>({window:full,mode:'log',quote:null}));
  chart._fullLayout.yaxis.range=[62,78];handlers.plotly_relayout();
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(chart._fullLayout.yaxis.range,axis.fitWindow([soxl],full,'log').range);
  assert.equal(chart.layout.yaxis.ticktext.length,6);
  chart._fullLayout.xaxis.range=future;
  chart._fullLayout.yaxis.range=[1,3];
  handlers.plotly_relayout();
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(chart._fullLayout.xaxis.range.map(Date.parse),future.map(Date.parse),'Releasing a future pan must not snap to historical dates');
  assert.deepEqual(chart._fullLayout.yaxis.range,[1,3],'A valid manual zoom must survive fitting callbacks');
  handlers.plotly_afterplot();
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(chart._fullLayout.xaxis.range.map(Date.parse),future.map(Date.parse),'Subsequent redraws preserve future navigation');
  assert.deepEqual(chart._fullLayout.yaxis.range,[1,3]);
  assert.ok(updates<8);
  console.log('Window-fit tests passed: sensible historical fit, readable ticks, persistent future pan/zoom, explicit projection fitting, UTC dates and extreme-range protection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
