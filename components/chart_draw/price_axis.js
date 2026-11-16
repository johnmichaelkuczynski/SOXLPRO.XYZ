(function(root) {
  'use strict';
  function label(value) {
    return '$' + value.toLocaleString('en-US', {
      notation:'standard',maximumFractionDigits:value < 0.001 ? 12 : 6
    });
  }
  function ticks(range, height, mode) {
    const count = Math.max(5, Math.min(8, Math.floor((Number(height) || 500) / 85)));
    if (!range || range.length !== 2 || !range.every(Number.isFinite)) return {};
    const lo = Math.min(...range), hi = Math.max(...range), span = hi - lo;
    if (!(span > 0)) return {};
    const raw=Array.from({length:count},(_,i)=>{
      const coordinate=lo+span*(i+0.5)/count;
      return mode==='log' ? 10**coordinate : coordinate;
    });
    const rounded=raw.map(value=>Number(value.toPrecision(2)));
    const transform=value=>mode==='log'?Math.log10(value):value;
    const readable=rounded.every((value,i)=>Number.isFinite(value) && value>0 &&
      transform(value)>lo && transform(value)<hi &&
      (!i || (transform(value)-transform(rounded[i-1]))/span*height>=30));
    const values=readable ? rounded : raw;
    return {tickmode:'array',tickvals:values,ticktext:values.map(label),
      tickprefix:'',tickformat:'',exponentformat:'none',showexponent:'none'};
  }
  function fit(prices, mode) {
    let min=Infinity,max=0;
    (prices||[]).forEach(value=>{if(Number.isFinite(value)&&value>0){min=Math.min(min,value);max=Math.max(max,value);}});
    if (!Number.isFinite(min)) return null;
    if (mode==='log') {
      const lo=Math.log10(min),hi=Math.log10(max);
      const padding=hi>lo?(hi-lo)*0.075:Math.log10(1.075);
      return [lo-padding,hi+padding];
    }
    const padding=max>min?(max-min)*0.075:max*0.075;
    return [Math.max(0,min-padding),max+padding];
  }
  function timestamp(value) {
    if(typeof value==='number') return value;
    // Plotly's timezone-less date strings are UTC chart coordinates, not the
    // browser's local timezone. Treating them as local causes relayout loops.
    let text=String(value||'').replace(' ','T');
    if(/^\d{4}-\d\d-\d\dT/.test(text) && !/(?:Z|[+-]\d\d:?\d\d)$/i.test(text)) text+='Z';
    return Date.parse(text);
  }
  function dateRange(range, allowed) {
    const bounds=allowed.map(timestamp);
    if (!range || range.length!==2) return bounds;
    const values=range.map(timestamp);
    if (!values.every(Number.isFinite) || values[1]<=values[0] ||
        values[1]<=bounds[0] || values[0]>=bounds[1]) return bounds;
    return [Math.max(values[0],bounds[0]),Math.min(values[1],bounds[1])];
  }
  const dateBounds=['1900-01-01T00:00:00Z','2200-01-01T00:00:00Z'];
  function navigationDateRange(range, fallback) {
    const values=Array.isArray(range)?range.map(timestamp):[];
    const bounds=dateBounds.map(timestamp);
    return values.length===2 && values.every(Number.isFinite) &&
      values[1]>values[0] && values[0]>=bounds[0] && values[1]<=bounds[1]
      ? values : fallback.map(timestamp);
  }
  function priceBounds(mode) { return mode==='log'?[-12,12]:[0,1e12]; }
  function navigationPriceRange(range, mode, fallback) {
    if(!Array.isArray(range) || range.length!==2 || !range.every(Number.isFinite) ||
        range[1]<=range[0]) return fallback.slice();
    const bounds=priceBounds(mode);
    const values=[Math.max(bounds[0],range[0]),Math.min(bounds[1],range[1])];
    return values[1]>values[0]?values:fallback.slice();
  }
  function fitWindow(traces, window, mode, quote, options) {
    const dates=window.map(timestamp),prices=[];
    (traces||[]).forEach(trace=>{
      const projection=trace.meta && trace.meta.channelLineIndex!==undefined;
      if (trace.visible===false || trace.visible==='legendonly' ||
          (projection && !(options && options.includeProjections))) return;
      const x=trace.x||[],y=trace.y||[];
      for(let i=0;i<Math.min(x.length,y.length);i++) {
        const when=timestamp(x[i]),price=Number(y[i]);
        if(when>=dates[0] && when<=dates[1] && Number.isFinite(price) && price>0 &&
            (!projection || (price>=1e-12 && price<=1e12)))
          prices.push(price);
      }
    });
    if(quote && timestamp(quote.observed_at)>=dates[0] && timestamp(quote.observed_at)<=dates[1] &&
        Number.isFinite(quote.price) && quote.price>0) prices.push(quote.price);
    const range=fit(prices,mode);
    if (!range) return null;
    let min=Infinity,max=0;
    prices.forEach(value=>{min=Math.min(min,value);max=Math.max(max,value);});
    return {range,min,max,count:prices.length,xRange:dates};
  }
  function install(chart, getOptions) {
    chart._priceAxisOptions = getOptions;
    if (chart._readablePriceAxis) return;
    let pending = false, queued = false;
    function refresh() {
      if (!chart._fullLayout || !chart.layout) return;
      if (pending) { queued=true;return; }
      const options=chart._priceAxisOptions(),axis=chart._fullLayout.yaxis;
      const xRange=navigationDateRange(chart._fullLayout.xaxis.range,options.window);
      const fitted=fitWindow(chart.data,options.window,options.mode,options.quote);
      if(!fitted) return;
      // Refresh labels, not the user's viewport. A valid pan/zoom must survive
      // mouse release and live-price updates, including future-only windows.
      const range=navigationPriceRange(axis.range,options.mode,fitted.range);
      const config=ticks(range,axis._length,options.mode);
      config.range=range;config.autorange=false;
      const limits=priceBounds(options.mode);
      config.minallowed=limits[0];config.maxallowed=limits[1];
      const update={};
      Object.keys(config).forEach(key=>{
        const current=key==='range'?axis.range:chart.layout.yaxis[key];
        if(JSON.stringify(current)!==JSON.stringify(config[key])) update['yaxis.'+key]=config[key];
      });
      const currentX=chart._fullLayout.xaxis.range.map(timestamp);
      if(currentX.some((value,i)=>Math.abs(value-xRange[i])>1))
        update['xaxis.range']=xRange.map(value=>new Date(value).toISOString());
      if(options.onNavigate) options.onNavigate(xRange);
      if(!Object.keys(update).length) return;
      update['yaxis.autorange']=false;
      pending = true;
      Promise.resolve(root.Plotly.relayout(chart,update)).finally(()=>{
        pending=false;
        // Do not lose a fast pan/zoom that arrived during the preceding update.
        if (queued) { queued=false; queueMicrotask(refresh); }
      });
    }
    chart.on('plotly_relayout',refresh);
    chart.on('plotly_afterplot',refresh);
    chart._readablePriceAxis = {refresh};
    refresh();
  }
  const api = {ticks,label,fit,dateRange,navigationDateRange,navigationPriceRange,
    priceBounds,dateBounds,fitWindow,install};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SOXLPriceAxis = api;
})(typeof window !== 'undefined' ? window : globalThis);
