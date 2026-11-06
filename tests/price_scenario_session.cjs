// Real app, real widgets, one open document; no mocked scenario estimates.
// Requires the app's saved market snapshot, just like the chart-session suite.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const readline = require('node:readline');
const net = require('node:net');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const port = Number(process.env.PRICE_SCENARIO_TEST_PORT || 5120);
const output = path.resolve('generated-artifacts/price-scenario');
fs.mkdirSync(output, {recursive: true});
const report = {checks: [], pageErrors: []};
const children = [];
let browser, page, completed = 0, navigations = 0;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, timeout = 90000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await check()) return;
    await sleep(100);
  }
  throw new Error(`Timed out: ${label}`);
}
function start(args, logName) {
  const child = spawn('python', args, {stdio: ['pipe', 'pipe', 'pipe']});
  children.push(child);
  const log = fs.createWriteStream(path.join(output, logName));
  child.stderr.pipe(log);
  return child;
}
async function stop(child) {
  if (child.exitCode !== null) return;
  const exited = once(child, 'exit');
  child.kill('SIGTERM');
  const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
  await exited;
  clearTimeout(timer);
}
async function chart() {
  let found;
  await until(async () => {
    for (const frame of page.frames()) {
      try {
        if (await frame.evaluate(() => !!document.querySelector('#chart .main-svg'))) {
          found = frame;
          return true;
        }
      } catch {}
    }
    return false;
  }, 'real chart initialized (saved market data must be available)');
  return found;
}
async function chartState(frame) {
  return frame.evaluate(() => ({
    lines: JSON.parse(JSON.stringify(lines)),
    x: [...chartDiv.layout.xaxis.range],
    y: [...chartDiv.layout.yaxis.range],
    token: window.__priceScenarioTestToken,
  }));
}
const markdown = () => page.locator('[data-testid="stMarkdownContainer"]');
async function analysisState() {
  const heading = markdown().filter({hasText: /^Period Analysis:/});
  const summary = markdown().filter({hasText: /Start Price/}).filter({hasText: /Period Low/});
  assert.equal(await heading.count(), 1, 'existing period analysis heading');
  assert.equal(await summary.count(), 1, 'existing period analysis results');
  return [await heading.innerText(), await summary.innerText()];
}
async function signalState() {
  const daily = page.locator('[data-testid="stColumn"]')
    .filter({has: page.getByRole('heading', {name: 'Short-term signal (1 month)', exact: true})});
  assert.equal(await daily.count(), 1, 'existing daily signal');
  return [
    await markdown().filter({hasText: /Composite historical-range percentile:/}).innerText(),
    await daily.innerText(),
  ];
}

(async () => {
  // Never attach to or stop the user's running preview.
  await new Promise((resolve, reject) => {
    const socket = net.createServer();
    socket.once('error', reject);
    socket.listen(port, '127.0.0.1', () => socket.close(resolve));
  });
  const backend = start(['tests/session_server.py', 'backend', String(port), String(port)], 'backend.log');
  backend.stdout.pipe(fs.createWriteStream(path.join(output, 'backend-stdout.log')));
  await until(async () => {
    if (backend.exitCode !== null) throw Error('Isolated backend exited; see backend.log');
    try { return (await fetch(`http://127.0.0.1:${port}/_stcore/health`)).ok; }
    catch { return false; }
  }, 'isolated backend health');
  const decoder = start(['tests/price_scenario_messages.py'], 'decoder.log');
  readline.createInterface({input: decoder.stdout}).on('line', line => {
    if (JSON.parse(line).scenarioFinished) completed++;
  });
  browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH,
    args: ['--no-sandbox'],
  });
  page = await browser.newPage({viewport: {width: 1440, height: 1100}});
  page.on('pageerror', error => report.pageErrors.push(error.message));
  page.on('framenavigated', frame => { if (frame === page.mainFrame()) navigations++; });
  page.on('websocket', ws => ws.on('framereceived', ({payload}) => {
    if (Buffer.isBuffer(payload)) decoder.stdin.write(payload.toString('base64') + '\n');
  }));
  await page.goto(`http://127.0.0.1:${port}/`, {waitUntil: 'domcontentloaded'});
  let frame = await chart();
  // Complete a real drawn-line gesture in the existing Plotly component.
  // Activate the toolbar by keyboard; the tall iframe's floating controls can
  // overlap the toolbar during parent-page auto-scroll.
  await frame.locator('#drawBtn').focus();
  await frame.locator('#drawBtn').press('Enter');
  await frame.locator('#chart .nsewdrag').scrollIntoViewIfNeeded();
  const plot = await frame.locator('#chart .nsewdrag').boundingBox();
  assert.ok(plot && plot.width > 100, 'chart drawing surface');
  assert.ok(plot.y + plot.height * .4 > 0 && plot.y + plot.height * .65 < 1100,
    'draw gesture must be inside the browser viewport');
  await page.mouse.move(plot.x + plot.width * .3, plot.y + plot.height * .65);
  await page.mouse.down();
  await page.mouse.move(plot.x + plot.width * .55, plot.y + plot.height * .4, {steps: 12});
  await page.mouse.up();
  await until(async () => (await chartState(await chart())).lines.length > 0, 'drawn line accepted');
  frame = await chart();
  await frame.locator('#selectBtn').click();
  await frame.locator('#start-date').fill('2023-01-03');
  await frame.locator('#end-date').fill('2024-01-03');
  await frame.getByRole('button', {name: 'Apply date range'}).click();
  await frame.getByRole('button', {name: 'Analyze This Period', exact: true}).click();
  await page.getByRole('heading', {name: /Period Analysis:/}).waitFor({timeout: 90000});
  // Allow the analysis' full-app round trip to settle before capturing state.
  await sleep(1500);
  frame = await chart();
  await frame.evaluate(async () => {
    window.__priceScenarioTestToken = crypto.randomUUID();
    setMode('pan');
    await Plotly.relayout(chartDiv, {
      'xaxis.range': ['2023-03-01', '2025-03-01'], 'yaxis.range': [1, 2],
    });
  });
  const baseline = await chartState(frame);
  const analysis = await analysisState();
  const signal = await signalState();
  const initialNavigations = navigations;
  const sliderFrame = page.frameLocator('iframe[src*="price_probability_slider"]');
  const slider = sliderFrame.getByRole('slider', {name: 'Hypothetical entry price (USD)'});
  const timeframe = page.locator('[data-testid="stSelectbox"]')
    .filter({has: page.getByText('Timeframe', {exact: true})}).getByRole('combobox');
  const price = async () => Number(await slider.inputValue());
  const latest = await price();
  assert.ok(latest >= 1 && latest <= 500, 'latest-price initial selection');

  async function dragPrice(offset, toMaximum = false) {
    await slider.scrollIntoViewIfNeeded();
    const bounds = await slider.boundingBox();
    // Native Chromium range thumb is 20px wide. Its travel excludes half a
    // thumb at each endpoint; the range element's center is NOT the thumb.
    const x = bounds.x + 10 + ((await price()) - 1) / 499 * (bounds.width - 20);
    const y = bounds.y + bounds.height / 2;
    assert.ok(y > 0 && y < page.viewportSize().height, 'visible slider thumb');
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(toMaximum ? bounds.x + bounds.width - 10 : x + offset, y, {steps: 12});
    await page.mouse.up();
  }

  async function preserved(label) {
    assert.deepEqual(await chartState(await chart()), baseline, `${label}: drawing, zoom and iframe`);
    assert.deepEqual(await analysisState(), analysis, `${label}: analysis results`);
    assert.deepEqual(await signalState(), signal, `${label}: existing signals`);
    assert.equal(navigations, initialNavigations, `${label}: no document navigation`);
    assert.equal(await page.locator('[data-testid="stException"]').count(), 0);
    report.checks.push({name: label, completedFragments: completed, preserved: true});
  }
  async function update(label, action) {
    const before = completed;
    await action();
    await until(() => completed > before, `${label}: successful scenario fragment`);
    await preserved(label);
  }
  async function choose(label, days) {
    await update(label, async () => {
      await timeframe.click();
      await page.getByRole('option', {name: label, exact: true}).click();
    });
    assert.ok(await page.getByText(new RegExp(`${days} trading sessions · History through`)).count());
    assert.equal(await price(), latest, 'horizon preserves price');
  }
  await choose('One month', 21);
  await choose('Six months', 126);
  await choose('Twelve months', 252);
  await choose('One month', 21);
  await update('desktop thumb drag', () => dragPrice(30));
  const dragged = await price();
  report.draggedPrice = dragged;
  assert.notEqual(dragged, latest, 'physical drag changes price');
  await update('keyboard adjustment', () => slider.press('ArrowRight'));
  const keyboardPrice = await price();
  report.keyboardPrice = keyboardPrice;
  assert.ok(Math.abs(keyboardPrice - dragged - .01) < .001,
    `ArrowRight must increase ${dragged} by .01, got ${keyboardPrice}`);
  await update('unsupported upper price', () => dragPrice(0, true));
  assert.equal(await price(), 500);
  await page.getByText(/This price is outside the observed historical range/).waitFor();
  assert.equal(await page.getByText('Historical probability of finishing higher', {exact: true}).count(), 0);
  assert.equal(await page.getByText('Median future price', {exact: true}).count(), 0);
  await update('latest-price reset', () => page.getByRole('button', {name: 'Use latest price', exact: true}).click());
  await until(async () => (await price()) === latest, 'reset component displays latest price');
  await page.screenshot({path: path.join(output, 'desktop.jpg')});

  await page.setViewportSize({width: 390, height: 844});
  await slider.scrollIntoViewIfNeeded();
  for (const control of [slider, timeframe, page.getByRole('button', {name: 'Use latest price', exact: true})]) {
    const box = await control.boundingBox();
    assert.ok(box && box.width > 0 && box.x >= 0 && box.x + box.width <= 391, 'mobile control fits viewport');
  }
  await update('mobile thumb drag', () => dragPrice(35));
  assert.notEqual(await price(), latest);
  await update('mobile latest-price reset', () => page.getByRole('button', {name: 'Use latest price', exact: true}).click());
  await until(async () => (await price()) === latest, 'mobile reset component displays latest price');
  await choose('Six months', 126);
  await slider.scrollIntoViewIfNeeded();
  await page.screenshot({path: path.join(output, 'mobile.jpg')});
  assert.deepEqual(report.pageErrors, [], 'no browser errors');
  report.passed = true;
})().catch(error => {
  report.passed = false;
  report.failure = error.stack;
  process.exitCode = 1;
}).finally(async () => {
  if (!report.passed && page) {
    await page.screenshot({path: path.join(output, 'failure.jpg')}).catch(() => {});
    fs.writeFileSync(path.join(output, 'failure.html'), await page.content().catch(() => ''));
  }
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (browser) await browser.close();
  await Promise.all(children.map(stop));
});
