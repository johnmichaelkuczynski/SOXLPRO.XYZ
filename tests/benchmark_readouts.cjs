const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 try {
  const page=await browser.newPage({viewport:{width:1200,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(pathToFileURL(path.resolve('components/chart_draw/index.html')).href);
  await page.waitForFunction(()=>typeof Plotly!=='undefined');
  await page.evaluate(()=>window.postMessage({type:'streamlit:render',args:{
   dates:['2020-01-01','2026-10-21'],prices:[10,100],
   selected_benchmarks:['QQQ','VIX','BTC'],
   custom_label:'SBR.US',custom_dates:['2026-10-21'],custom_actual:[50],custom_prices:[10],
   market_feed:{benchmark_quotes:{
    QQQ:{price:704.63,currency:'USD',observed_at:new Date().toISOString(),source:'Yahoo Finance'},
    VIX:{price:18.92,unit:'points',observed_at:new Date().toISOString(),source:'Yahoo Finance'},
    BTC:{price:81244.97,currency:'USD',observed_at:'2020-01-01T16:00:00Z',source:'Yahoo Finance',error:'TimeoutError'}
   }}
  }},'*'));
  await page.waitForFunction(()=>document.getElementById('chart')._fullLayout);
  const cards=page.locator('#benchmark-price-cards');
  await cards.getByText('$704.63',{exact:true}).waitFor();
  assert.ok((await cards.innerText()).includes('18.92 points'));
  assert.ok((await cards.innerText()).includes('Update unavailable'));
  assert.ok((await cards.innerText()).includes('Quote unavailable'));
  const before=await page.evaluate(()=>JSON.stringify({x:chartDiv.layout.xaxis.range,y:chartDiv.layout.yaxis.range,lines}));
  await page.evaluate(()=>acceptMarketFeed({benchmark_quotes:{
    QQQ:{price:705.25,currency:'USD',observed_at:new Date().toISOString(),source:'Yahoo Finance'},
    'SBR.US':{price:51.25,currency:'USD',observed_at:new Date().toISOString(),source:'EODHD'}
  }}));
  await cards.getByText('$705.25',{exact:true}).waitFor();
  await cards.getByText('$51.25',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>JSON.stringify({x:chartDiv.layout.xaxis.range,y:chartDiv.layout.yaxis.range,lines})),before);
  await page.setViewportSize({width:400,height:850});
  assert.ok(await page.locator('#benchmark-readouts').isVisible());
  assert.deepEqual(errors,[]);
  console.log('PASS benchmark readouts: prices, index units, stale/error/pending states, custom quote updates, mobile, no chart reset.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
