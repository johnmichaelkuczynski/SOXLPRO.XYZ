const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROMIUM_PATH,
    args:['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport:{width:1200,height:1100}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(path.resolve('components/chart_draw/index.html')).href);
    await page.waitForFunction(() => typeof Plotly !== 'undefined');
    await page.evaluate(() => window.postMessage({type:'streamlit:render',args:{
      dates:['2020-01-01','2026-10-21'], prices:[10,100],
      lines:[{x1:'2020-01-01',x2:'2026-10-21',y1:10,y2:100,
        color:'#399349',label:'Lower Channel Line'}]
    }}, '*'));
    await page.waitForFunction(() => document.getElementById('chart')._fullLayout);
    await page.waitForTimeout(400);
    const original = await page.evaluate(() => ({
      lines:JSON.stringify(lines), prices:JSON.stringify(chartData.prices),
      x:JSON.stringify(chartDiv.layout.xaxis.range)
    }));
    for (const scale of ['log','linear']) {
      await page.evaluate(scale => setScale(scale), scale);
      await page.waitForTimeout(150);
      await page.locator('#tiltBtn').click();
      const range = () => page.evaluate(() => chartDiv.layout.yaxis.range.slice());
      const before = await range();
      const box = await page.locator('#chart').boundingBox();
      await page.mouse.move(box.x+350,box.y+420);
      await page.mouse.down();
      await page.mouse.move(box.x+350,box.y+270,{steps:12});
      await page.mouse.up();
      await page.waitForTimeout(150);
      const after = await range();
      assert.ok(after[1]-after[0] < before[1]-before[0], scale+' steepens');
      assert.ok(Math.abs(after[0]+after[1]-before[0]-before[1])<1e-7);
      await page.mouse.move(box.x+350,box.y+270);
      await page.mouse.down();
      await page.mouse.move(box.x+350,box.y+420,{steps:12});
      await page.mouse.up();
      await page.waitForTimeout(150);
      const flattened = await range();
      assert.ok(flattened[1]-flattened[0] > after[1]-after[0], scale+' flattens');
      await page.locator('#tiltBtn').click();
      assert.equal(await page.evaluate(() => currentMode),'pan');
      const preserved = await page.evaluate(() => ({
        lines:JSON.stringify(lines),prices:JSON.stringify(chartData.prices),
        x:JSON.stringify(chartDiv.layout.xaxis.range)
      }));
      assert.deepEqual(preserved,original);
      await page.evaluate(() => resetView());
      assert.deepEqual(await range(),await page.evaluate(() => yAxisRange()));
    }
    assert.deepEqual(errors,[]);
    console.log('PASS: real pointer drags steepen/flatten both scales; data, lines and dates unchanged; navigation and reset restored.');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exit(1);});
