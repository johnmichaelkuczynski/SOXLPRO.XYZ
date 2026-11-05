const {chromium}=require('playwright'), assert=require('node:assert/strict'), fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--no-sandbox'],
    executablePath:process.env.CHROMIUM_PATH||'/repl/tools/bin/chromium'});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1100}});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    let posts=0;page.on('request',request=>{
      if(request.method()==='POST'&&request.url().endsWith('/api/diagnostics/run'))posts++;
    });
    await page.goto('https://'+process.env.REPLIT_DEV_DOMAIN+'/',{waitUntil:'domcontentloaded',timeout:60000});
    let controls,chart;
    for(let i=0;i<180;i++){
      controls=page.frames().find(frame=>frame.url().includes('/component/app_diagnostics.'));
      for(const frame of page.frames()){
        if(await frame.locator('#benchmark-toggle-grid input').count()===8)chart=frame;
      }
      if(controls&&chart&&await chart.evaluate(()=>Boolean(chartDiv._fullLayout&&!chartRenderTask)))break;
      await new Promise(resolve=>setTimeout(resolve,250));
    }
    assert(controls&&chart,'Diagnostics button and graph must both be present');
    await chart.evaluate(()=>{
      window.__beforeDiagnostics={svg:chartDiv.querySelector('.main-svg'),lines:JSON.stringify(lines),
        axes:JSON.stringify([chartDiv.layout.xaxis.range,chartDiv.layout.yaxis.range]),
        selection:JSON.stringify(benchmarkVisibility)};
    });
    const start=Date.now();
    await controls.getByRole('button',{name:'Run full diagnostics',exact:true}).click();
    await controls.waitForFunction(()=>document.getElementById('run').disabled,{},{timeout:5000});
    await controls.waitForFunction(()=>!document.getElementById('run').disabled &&
      !document.getElementById('download').hidden,{},{timeout:230000});
    const report=await controls.locator('#download').evaluate(async link=>await(await fetch(link.href)).json());
    fs.writeFileSync('/tmp/soxl-live-diagnostic-result.json',JSON.stringify(report,null,2));
    assert.equal(posts,1,'One click must issue exactly one run request');
    assert(report.checks.length>=65,'Report must include browser and server checks');
    assert(report.checks.some(row=>row.name==='User chart continuity and settings preserved'&&row.status==='pass'));
    assert(report.checks.some(row=>row.name==='Daily signals'));
    assert(report.checks.some(row=>row.name==='OpenAI answer generation'));
    assert(report.checks.some(row=>row.name==='Polygon options chain and quotes'));
    const continuity=await chart.evaluate(()=>({
      svg:chartDiv.querySelector('.main-svg')===window.__beforeDiagnostics.svg,
      lines:JSON.stringify(lines)===window.__beforeDiagnostics.lines,
      axes:JSON.stringify([chartDiv.layout.xaxis.range,chartDiv.layout.yaxis.range])===window.__beforeDiagnostics.axes,
      selection:JSON.stringify(benchmarkVisibility)===window.__beforeDiagnostics.selection
    }));
    assert(Object.values(continuity).every(Boolean),'Diagnostics must not rebuild or change the user graph');
    const incomplete=report.checks.some(row=>row.status!=='pass');
    const summary=await controls.locator('#summary').textContent();
    if(incomplete)assert(!summary.includes('All listed checks passed'));
    assert.deepEqual(errors,[]);
    const counts={};
    for(const row of report.checks)counts[row.status]=(counts[row.status]||0)+1;
    console.log('PASS: one click ran '+report.checks.length+' browser/server checks in '+Math.round((Date.now()-start)/1000)+' seconds; '+JSON.stringify(counts));
    console.log('PASS: report is downloadable; no confirmation or second submit; same graph, drawings, axes and selections.');
    for(const row of report.checks.filter(row=>row.status==='fail'))
      console.log('REPORTED FAILURE: '+row.name+' — '+row.detail);
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
