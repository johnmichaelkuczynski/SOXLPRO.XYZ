const {chromium}=require('playwright');
const http=require('node:http'), fs=require('node:fs'), path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve('components/chart_draw');
(async()=>{
  const server=http.createServer((request,response)=>{
    const file=path.resolve(root,'.'+new URL(request.url,'http://local').pathname);
    if(!file.startsWith(root+path.sep)){response.writeHead(403);return response.end()}
    try{
      response.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':'text/html');
      response.end(fs.readFileSync(file));
    }catch(_){response.writeHead(404);response.end()}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/repl/tools/bin/chromium',args:['--no-sandbox'],headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1400,height:1200}});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://127.0.0.1:'+server.address().port+'/index.html');
    const rows=await page.evaluate(async()=>{
      const dates=[],prices=[];
      for(let i=0;i<500;i++){
        dates.push(new Date(Date.UTC(2024,0,1+i)).toISOString().slice(0,10));
        prices.push(30*Math.exp(i*.001+Math.sin(i/15)*.15));
      }
      const args={dates,prices,lines:[],selected_benchmarks:[],future_end:'2031-01-01'};
      for(const name of SOXLBenchmarkVisibility.names){
        args[name.toLowerCase()+'_dates']=dates;
        args[name.toLowerCase()+'_prices']=prices.map(p=>p*.7);
        args[name.toLowerCase()+'_actual']=prices;
      }
      postMessage({type:'streamlit:render',args},location.origin);
      for(let i=0;i<100;i++){
        if(chartDiv._fullLayout&&!chartRenderTask&&chartDiv.querySelector('.js-line'))break;
        await new Promise(resolve=>setTimeout(resolve,50));
      }
      for(const name of SOXLBenchmarkVisibility.names)benchmarkQuotes[name]={price:50,observed_at:new Date().toISOString()};
      const prefs=sessionStorage.getItem('soxl-chart-benchmark-visibility-soxl-only');
      const rows=await runSOXLChartDiagnostics();
      if(sessionStorage.getItem('soxl-chart-benchmark-visibility-soxl-only')!==prefs)
        throw Error('Diagnostics modified actual chart preferences');
      return rows;
    });
    for(const row of rows)console.log(row.status+': '+row.name+' — '+row.detail);
    assert.deepEqual(rows.filter(row=>row.status==='fail'),[]);
    assert.deepEqual(errors,[]);
    assert(rows.some(row=>row.name==='Benchmark hide/show without blanking'&&row.status==='pass'));
    assert(rows.some(row=>row.name==='User chart continuity and settings preserved'&&row.status==='pass'));
    console.log('PASS: diagnostics exercise an isolated real chart and preserve user preferences.');
  }finally{await browser.close();await new Promise(resolve=>server.close(resolve))}
})().catch(error=>{console.error(error);process.exit(1)});
