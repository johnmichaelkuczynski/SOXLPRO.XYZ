// Real app + real gateway + real WebSockets. No page reloads after initial goto.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const fs = require('node:fs');
const readline = require('node:readline');
const net = require('node:net');
const path = require('node:path');
const assert = require('node:assert/strict');

const output = path.resolve('generated-artifacts/chart-session');
const port = Number(process.env.SESSION_TEST_PORT || 5100);
const backendPort = port + 1;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const report = {scenarios: [], pageErrors: [], sockets: {opened: 0, closed: 0}};
let browser, backend, gateway, decoder, page;
let fragmentRuns = 0;
fs.mkdirSync(output, {recursive: true});

function start(mode, listen) {
  const child = spawn('python', ['tests/session_server.py', mode, String(listen), String(backendPort)],
    {stdio: ['ignore', 'pipe', 'pipe']});
  const log = fs.createWriteStream(path.join(output, `${mode}.log`), {flags: 'a'});
  child.stdout.pipe(log); child.stderr.pipe(log);
  return child;
}
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  const exited = once(child, 'exit');
  child.kill('SIGTERM');
  const force = setTimeout(() => child.kill('SIGKILL'), 5000);
  await exited;
  clearTimeout(force);
}
async function until(check, label, timeout = 90000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await check()) return;
    await sleep(250);
  }
  throw Error(`Timed out: ${label}`);
}
async function ready() {
  await until(async () => {
    try { return (await fetch(`http://127.0.0.1:${port}/_gateway/ready`)).ok; }
    catch { return false; }
  }, 'isolated backend ready');
}
async function requireFreePort(port) {
  await new Promise((resolve, reject) => {
    const socket = net.createServer();
    socket.once('error', reject);
    socket.listen(port, '127.0.0.1', () => socket.close(resolve));
  });
}
async function chart(page) {
  let found;
  await until(async () => {
    for (const frame of page.frames()) {
      try {
        if (await frame.evaluate(() => !!document.querySelector('#chart .main-svg') &&
          document.getElementById('chart')._fullLayout?.width > 0)) {
          found = frame; return true;
        }
      } catch {}
    }
    return false;
  }, 'visible initialized chart');
  assert.equal(await page.locator('[data-testid="stException"]').count(), 0,
    'Streamlit exception');
  assert.equal(await page.locator('#soxl-preview-recovery').count(), 0,
    'fatal recovery panel is not automatic recovery');
  return found;
}
async function snapshot(frame) {
  return frame.evaluate(() => ({
    lines: JSON.parse(JSON.stringify(lines)),
    x: [...chartDiv.layout.xaxis.range], y: [...chartDiv.layout.yaxis.range],
    token: window.__sessionTestToken,
  }));
}
async function seed(page) {
  const frame = await chart(page);
  await frame.evaluate(async () => {
    window.__sessionTestToken = crypto.randomUUID();
    setMode('draw');
    // Use the same Plotly drawing event handler as a completed mouse gesture.
    await Plotly.relayout(chartDiv, {shapes: [{
      type: 'line', x0: '2024-01-01', x1: '2025-01-01', y0: 20, y1: 40,
    }]});
  });
  await until(async () => (await snapshot(await chart(page))).lines.length > 0,
    'drawing accepted by component');
  await sleep(1500); // allow the setComponentValue server round trip to settle
  const settled = await chart(page);
  await settled.evaluate(async () => {
    window.__sessionTestToken ||= crypto.randomUUID();
    setMode('pan');
    await Plotly.relayout(chartDiv, {
      'xaxis.range': ['2023-01-01', '2026-01-01'], 'yaxis.range': [1, 2],
    });
  });
  return snapshot(settled);
}

(async () => {
  // Refuse occupied ports rather than accidentally testing another server.
  await requireFreePort(port);
  await requireFreePort(backendPort);
  gateway = start('gateway', port);
  backend = start('backend', backendPort);
  await ready();
  browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROMIUM_PATH,
    args: ['--no-sandbox']});
  const context = await browser.newContext({viewport: {width: 1440, height: 1100}});
  decoder = spawn('python', ['tests/session_messages.py']);
  decoder.stderr.pipe(process.stderr);
  readline.createInterface({input: decoder.stdout}).on('line', line => {
    if (JSON.parse(line).chartFragmentFinished) fragmentRuns++;
  });
  let activeSocket, blockSockets = false, navigations = 0;
  await context.routeWebSocket(/\/_stcore\/stream/, ws => {
    if (blockSockets) { ws.close(); return; }
    activeSocket = ws;
    const server = ws.connectToServer();
    ws.onMessage(message => server.send(message));
    server.onMessage(message => {
      if (Buffer.isBuffer(message)) decoder.stdin.write(message.toString('base64') + '\n');
      ws.send(message);
    });
  });
  page = await context.newPage();
  page.on('pageerror', e => report.pageErrors.push(e.message));
  page.on('framenavigated', frame => { if (frame === page.mainFrame()) navigations++; });
  page.on('websocket', ws => {
    report.sockets.opened++;
    ws.on('close', () => report.sockets.closed++);
  });
  await page.goto(`http://127.0.0.1:${port}/`, {waitUntil: 'domcontentloaded'});
  await chart(page);
  const initialNavigations = navigations;
  const before = await seed(page);

  // Observe successful execution of the actual chart fragment, even when
  // unchanged cached data causes Streamlit to reuse the existing iframe HTML.
  let frame = await chart(page);
  const count = fragmentRuns;
  await until(() => fragmentRuns > count, 'timed chart fragment finished', 75000);
  const refreshed = await snapshot(await chart(page));
  assert.deepEqual(refreshed, before, 'timed fragment must retain drawing, viewport, and iframe');
  report.scenarios.push({name: 'timed-fragment', retained: true});
  await page.screenshot({path: path.join(output, 'fragment.jpg')});

  const opened = report.sockets.opened;
  blockSockets = true;
  activeSocket.close({code: 1012, reason: 'Regression: transient connection loss'});
  await sleep(3000);
  blockSockets = false;
  await until(() => report.sockets.opened > opened, 'WebSocket reconnect');
  frame = await chart(page);
  const updateCount = fragmentRuns;
  await until(() => fragmentRuns > updateCount, 'chart fragment after reconnect', 75000);
  const reconnected = await snapshot(await chart(page));
  assert.deepEqual(reconnected, before, 'short disconnect must retain chart state');
  report.scenarios.push({name: 'websocket-loss', retained: true});
  await page.screenshot({path: path.join(output, 'reconnected.jpg')});

  const restartBefore = await snapshot(await chart(page));
  const priorOpened = report.sockets.opened;
  report.oldBackendPid = backend.pid;
  await stop(backend);
  await sleep(3000);
  backend = start('backend', backendPort);
  report.newBackendPid = backend.pid;
  await ready();
  await until(() => report.sockets.opened > priorOpened, 'restart reconnect');
  frame = await chart(page);
  const restartCount = fragmentRuns;
  await until(() => fragmentRuns > restartCount, 'chart fragment after restart', 75000);
  const restarted = await snapshot(await chart(page));
  // Record retention separately: process-local session state is not durable.
  report.scenarios.push({name: 'backend-restart', recovered: true,
    drawingsRetained: JSON.stringify(restarted.lines) === JSON.stringify(restartBefore.lines),
    viewportRetained: JSON.stringify([restarted.x, restarted.y]) ===
      JSON.stringify([restartBefore.x, restartBefore.y]),
    iframeRetained: restarted.token === restartBefore.token,
    before: restartBefore, after: restarted});
  assert.deepEqual(restarted.lines, restartBefore.lines, 'restart must retain open-tab drawings');
  assert.deepEqual([restarted.x, restarted.y], [restartBefore.x, restartBefore.y],
    'restart must retain open-tab viewport');
  await page.screenshot({path: path.join(output, 'restarted.jpg')});
  assert.equal(navigations, initialNavigations, 'test must keep the same document open');
  assert.deepEqual(report.pageErrors, [], 'browser errors during recovery');
  report.fragmentRuns = fragmentRuns;
  report.extraNavigations = navigations - initialNavigations;
  report.passed = true;
})().catch(error => {
  report.passed = false; report.failure = error.stack;
  process.exitCode = 1;
}).finally(async () => {
  if (!report.passed && page) {
    await page.screenshot({path: path.join(output, 'failure.jpg')}).catch(() => {});
  }
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (browser) await browser.close();
  await Promise.all([stop(backend), stop(gateway), stop(decoder)]);
});
