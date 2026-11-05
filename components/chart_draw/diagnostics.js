// Exercise an isolated copy of the real chart. Never operate on the user's lines.
(function () {
  let running = null;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function until(predicate, timeout = 12000) {
    const start = performance.now();
    while (performance.now() - start < timeout) {
      if (predicate()) return;
      await sleep(40);
    }
    throw Error('The operation did not finish within its time budget.');
  }
  async function run() {
    const rows = [];
    async function check(name, fn, group = 'Chart interaction') {
      const start = performance.now();
      try {
        const detail = await fn();
        rows.push({name, group, status:'pass', detail, ms:Math.round(performance.now()-start)});
      } catch (error) {
        rows.push({name, group, status:'fail', detail:error.message, ms:Math.round(performance.now()-start)});
      }
    }
    function assert(condition, message) { if (!condition) throw Error(message); }
    const original = {
      svg:chartDiv.querySelector('.main-svg'),
      lines:JSON.stringify(lines),
      selected:JSON.stringify(benchmarkVisibility),
      axes:JSON.stringify([chartDiv.layout.xaxis.range, chartDiv.layout.yaxis.range])
    };
    await check('Displayed SOXL chart', () => {
      assert(original.svg && chartDiv.querySelector('.scatterlayer .js-line'), 'No rendered price line.');
      assert(chartData?.prices.length > 1, 'SOXL price series is missing.');
      assert(chartDiv.data.some(t=>t.name==='SOXL' && t.visible!==false && t.visible!=='legendonly'), 'SOXL is hidden.');
      return `${chartData.prices.length} actual SOXL points; price line and SVG present.`;
    });
    await check('Chart controls present', () => {
      const ids=['drawBtn','undoBtn','medianLineBtn','upperChannelBtn','lowerChannelBtn',
        'selectBtn','axisAreaToggle','quick-fit','logScaleBtn','linearScaleBtn','heightSlider',
        'widthSlider','futureHorizon','rail-extend-date','projection-line'];
      assert(ids.every(id=>document.getElementById(id)), 'One or more required chart controls are missing.');
      assert(document.querySelectorAll('#benchmark-toggle-grid input').length===8, 'Benchmark controls missing.');
      return `${ids.length} required controls and eight benchmark selectors present.`;
    });
    for(const name of SOXLBenchmarkVisibility.names) {
      await check(name+' chart data', () => {
        const dates=chartData[name.toLowerCase()+'_dates'], values=chartData[name.toLowerCase()+'_prices'];
        assert(dates?.length>1 && dates.length===values?.length, 'No usable overlay points.');
        assert(values.every(v=>Number.isFinite(v)&&v>0), 'Invalid overlay price.');
        return `${values.length} chart-ready comparison points; hidden series remain available.`;
      }, 'Benchmarks');
      await check(name+' visible quote readout',()=>{
        const quote=benchmarkQuotes[name]||{};
        assert(Number.isFinite(quote.price)&&quote.price>0&&Number.isFinite(Date.parse(quote.observed_at)),
          'The displayed benchmark quote is unavailable or has no valid observation time.');
        return `Latest available observation: ${quote.price}; ${quote.observed_at}. Not a guarantee of real-time data.`;
      },'Quote readouts');
    }
    let frame;
    try {
      frame=document.createElement('iframe');
      frame.setAttribute('aria-hidden','true');frame.tabIndex=-1;
      frame.style.cssText='position:absolute;left:-100000px;top:0;width:1200px;height:1600px;border:0;pointer-events:none';
      const ready = new Promise((resolve, reject) => {
        const timer=setTimeout(()=>{window.removeEventListener('message', listener);reject(Error('Isolated chart did not initialize.'));},15000);
        function listener(event) {
          if(event.source!==frame.contentWindow || event.data?.type!=='streamlit:componentReady')return;
          clearTimeout(timer);window.removeEventListener('message',listener);resolve();
        }
        window.addEventListener('message',listener);
      });
      frame.src=location.pathname+'?diagnostics_sandbox=1';
      document.body.append(frame);
      await ready;
      const w=frame.contentWindow;
      w.postMessage({type:'streamlit:render',args:{...chartData,lines:[],selected_benchmarks:[],
        chart_height:900,market_feed:marketFeed}},location.origin);
      await until(()=>w.chartDiv?._fullLayout && !w.chartRenderTask && w.chartDiv.querySelector('.js-line'),15000);
      async function settled() {
        await sleep(60);
        await until(()=>!w.chartRenderTask && !w.pendingChartRender);
        assert(w.document.getElementById('chart-render-error').hidden, 'The chart displayed a rendering error.');
      }
      await check('Benchmark hide/show without blanking',async()=>{
        const svg=w.chartDiv.querySelector('.main-svg');
        const axes=JSON.stringify([w.chartDiv.layout.xaxis.range,w.chartDiv.layout.yaxis.range]);
        let blanks=0, sampling=true;
        function sample(){
          if(!sampling)return;
          if(w.chartDiv.querySelector('.main-svg')!==svg||!w.chartDiv.querySelector('.js-line'))blanks++;
          w.requestAnimationFrame(sample);
        }
        sample();
        try {
          for(const name of w.SOXLBenchmarkVisibility.names){
            const checkbox=w.document.querySelector(`[data-benchmark="${name}"]`) ||
              [...w.document.querySelectorAll('#benchmark-toggle-grid input')].find(x=>x.getAttribute('aria-label')===`Show ${name} on chart`);
            assert(checkbox, name+' checkbox missing.');
            const trace=w.chartDiv.data.find(x=>x.name===name);
            assert(trace, name+' trace missing.');
            checkbox.click();await settled();
            assert(trace.visible!==false&&trace.visible!=='legendonly',name+' did not become visible.');
            checkbox.click();await settled();
            assert(trace.visible===false||trace.visible==='legendonly',name+' did not hide.');
          }
        } finally {sampling=false}
        assert(blanks===0,`${blanks} blank animation frames detected.`);
        assert(JSON.stringify([w.chartDiv.layout.xaxis.range,w.chartDiv.layout.yaxis.range])===axes,'Axis ranges changed.');
        return 'All eight series toggled on/off; same SVG, unchanged axes, zero sampled blank frames.';
      });
      await check('Automatic channel lines',async()=>{
        for(const id of ['medianLineBtn','upperChannelBtn','lowerChannelBtn']){
          w.document.getElementById(id).click();await settled();
        }
        assert(w.lines.length===3,'Expected three generated channel lines.');
        assert(w.lines.every(line=>Object.values(line).every(value=>typeof value!=='number'||Number.isFinite(value))), 'A generated line has an invalid coordinate.');
        return 'Median, upper and lower channel buttons generated three finite lines from the actual history.';
      });
      await check('Undo and erase line',async()=>{
        const before=w.lines.length;
        assert(before>0,'No generated line is available for this test.');
        w.eraseLastLine();await settled();assert(w.lines.length===before-1,'Erase did not remove the last line.');
        w.document.getElementById('undoBtn').click();await settled();
        assert(w.lines.length===before,'Undo did not restore the line.');
        return 'Erase removed a generated line; Undo restored it in the isolated chart.';
      });
      await check('Draw and analyze modes',async()=>{
        w.document.getElementById('drawBtn').click();await settled();
        assert(w.currentMode==='draw'&&w.chartDiv.layout.dragmode==='drawline','Draw mode failed.');
        w.document.getElementById('drawBtn').click();await settled();
        assert(w.currentMode==='pan','Navigation mode was not restored.');
        w.document.getElementById('selectBtn').click();await settled();
        assert(w.currentMode==='select','Analyze mode did not start.');
        w.document.getElementById('selectBtn').click();await settled();
        assert(w.currentMode==='pan','Analyze mode did not stop.');
        return 'Draw, navigation and analysis-selection modes switched correctly. Actual pointer drags are not simulated.';
      });
      await check('Linear and log price scales',async()=>{
        for(const mode of ['linear','log']){
          w.document.getElementById(mode==='log'?'logScaleBtn':'linearScaleBtn').click();await settled();
          assert(w.chartDiv.layout.yaxis.type===mode, mode+' scale did not activate.');
        }
        return 'Both price-scale buttons changed the rendered axis type.';
      });
      await check('Chart dimensions and Reset View',async()=>{
        const before=JSON.stringify(w.lines);
        w.setChartHeight(650);w.setChartWidth(140);await settled();
        assert(w.currentChartHeight===650&&w.currentChartWidth===140,'Size controls did not apply.');
        await w.Plotly.relayout(w.chartDiv,{'xaxis.range':['2023-01-01','2024-01-01'],'yaxis.range':[0,1]});
        w.resetView();await settled();
        assert(w.currentChartWidth===100&&w.currentChartHeight===900,'Reset did not restore chart dimensions.');
        assert(new Date(w.chartDiv.layout.xaxis.range[0]).getTime()===new Date(w.chartData.dates[0]).getTime(),'Reset did not restore full history.');
        assert(JSON.stringify(w.lines)===before,'Reset changed channel lines.');
        return 'Changed dimensions and zoom, then Reset View restored full history and normal size without deleting lines.';
      });
      await check('Future horizon',async()=>{
        w.setFutureHorizon('10');await settled();assert(w.futureHorizonYears===10,'Ten-year horizon failed.');
        w.setFutureHorizon('5');await settled();assert(w.futureHorizonYears===5,'Five-year horizon failed.');
        return 'Both future horizon changes applied.';
      });
      await check('Projection probability calculation',()=>{
        const model=w.getHitProbabilityModel();
        assert(model,'Historical probability model unavailable.');
        const p=w.estimateHitProbability(model.latestPrice*1.1,model.latestTimestamp+365.25*86400000);
        assert(Number.isFinite(p)&&p>=0&&p<=1,'Projection probability is not finite or within 0–100%.');
        return `A test target 10% above the last close returned ${(p*100).toFixed(2)}% by one year. This checks calculation, not predictive accuracy.`;
      });
      await check('Rotation / fit-screen view',async()=>{
        w.openRotationView();
        await until(()=>w.document.querySelector('#rotation-view img[src^="data:"]'),15000);
        return 'The fitted rotation view generated an actual chart image in the isolated chart.';
      });
    } catch(error) {
      rows.push({name:'Isolated chart test harness',group:'Chart interaction',status:'fail',detail:error.message});
    } finally {
      if(frame)frame.remove();
    }
    await check('User chart continuity and settings preserved',()=>{
      assert(chartDiv.querySelector('.main-svg')===original.svg,'The original graph was replaced.');
      assert(JSON.stringify(lines)===original.lines,'User-drawn lines changed.');
      assert(JSON.stringify(benchmarkVisibility)===original.selected,'Benchmark selections changed.');
      assert(JSON.stringify([chartDiv.layout.xaxis.range,chartDiv.layout.yaxis.range])===original.axes,'User zoom changed.');
      return 'Original SVG, drawings, benchmark selections and axis ranges are unchanged by diagnostics.';
    });
    rows.push({name:'Interaction coverage limits',group:'Coverage',status:'not_tested',
      detail:'Real mouse/touch dragging, every keyboard/browser combination, custom user strategies and every form submission are not fully exercised by this safe in-page run. No prediction accuracy is certified.'});
    return rows;
  }
  window.runSOXLChartDiagnostics=function(){
    if(!running)running=run().finally(()=>{running=null});
    return running;
  };
})();
