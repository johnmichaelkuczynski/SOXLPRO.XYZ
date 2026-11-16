const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('components/chart_draw/index.html','utf8');
const source=html.slice(html.indexOf('function publicPriceText(value)'),html.indexOf('function soxlMarketTrace()'));
const elements={};
const context={document:{getElementById:id=>elements[id]??=( {textContent:'',title:''} )},
  latestMarketQuote:{price:50.06,source:'Schwab',session:'Regular session',
    observed_label:'Nov 16, 2026 11:00 AM ET',observed_at:new Date().toISOString(),
    feed_warning:'Schwab quote may be delayed.',checked_at:new Date().toISOString()},
  marketFeedError:'Yahoo Finance update failed.',marketFeed:{checked:Date.now()}};
vm.createContext(context);vm.runInContext(source,context);
context.updateMarketFeedStatus();
for (const element of Object.values(elements))
  assert.doesNotMatch(element.textContent+' '+element.title,/schwab|yahoo/i);
assert.match(elements['market-feed-status'].textContent,/\$50\.06/);
context.latestMarketQuote=null;
context.marketFeedError='Schwab price unavailable. Authorize at /auth/schwab/connect.';
context.updateMarketFeedStatus();
for (const element of Object.values(elements))
  assert.doesNotMatch(element.textContent+' '+element.title,/schwab|yahoo/i);
assert.match(elements['market-feed-status'].textContent,/unavailable/);
assert.match(html,/payload\.quote\.source === 'Schwab'/,'Underlying source validation must stay unchanged');
console.log('Public price labels passed: no provider names in prices, hover text, session labels or feed errors; source validation retained.');
